#!/usr/bin/env python3
"""Every source coordinate the fixture tree carries, classified (#259 final).

The coordinate-domain decision (`spec/OwnIR.md` §4.2) narrows what a `line`
and a `column` may be. Before narrowing a contract, measure what the corpus
already holds against it — otherwise "no producer emits that" is a belief, and
"nothing else churns" is a hope.

This module is that measurement, and it is deliberately WIDER than the door:

* it reads every `.json` file under `tests/fixtures/`, not only the OwnIR
  documents, because the goldens are where the decision is most easily broken.
  `0` stays a legal line, so a summaries or verdict golden anchored at line 0
  must come through this change untouched; a census that only looked at inputs
  could not see that at all;
* it reaches every `line` / `column` slot at any depth and under any key, so a
  coordinate in a shape nobody thought to list is counted rather than missed.

Two classifications, and the split between them is the point:

* **value class** — where the value sits relative to the domain. `zero` is its
  own class rather than folded into `in-domain`: `0` means "unknown /
  file-level" and is the reference's own default for an absent line, so the
  count of zeros is the count of records this contract must go on accepting.
  `negative` and `above-int32` are representable coordinates violating the
  domain rule (`Location` in the cp1 taxonomy); `outside-int64` has no
  representable integer form at all (`Shape`). They are not one class, because
  they are not one mechanism — the same distinction #326's census had to
  discover the hard way.
* **door slot or observation** — a coordinate on an OwnIR *document* is
  subject to `load()`; one in a golden is an *output* of the analysis and the
  door never sees it. `SLOTS` below is the door inventory, and the census
  asserts it is neither stale nor short: a declared slot the tree cannot reach
  is a phantom, and both directions are reported.

Pure: no `ownlang` import and no side effects, like `verdict_census.py` beside
it — the fragment renderer reads it, so it must not be the untyped link.
Held to `mypy --strict` (see `files` in pyproject.toml).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")

# The domain (`spec/OwnIR.md` §4.2) and the representable integer form the
# domain sits inside, as LITERALS. Importing them from `ownlang` would make
# this census move with the contract it exists to measure against — the same
# self-consistency trap `tests/test_ownir_defensive_limits.py` records at the
# top of its own constant block.
LINE_MIN = 0
LINE_MAX = 2147483647
COLUMN_MIN = 1
COLUMN_MAX = 2147483647
INT64_MIN = -9223372036854775808
INT64_MAX = 9223372036854775807

# The keys that hold a source coordinate. `ctor_line` is deliberately absent:
# it is a service's constructor coordinate and travels the same door rule, but
# it is reached under its own key and appears in `SLOTS` below.
COORD_KEYS = ("line", "column", "ctor_line")

# The nesting keys of a flow body / event tree. A run of them collapses to one
# marker so that `functions[].body[].then[].else[].line` and a body nested
# thirty-two deep are ONE row: the census is about which slot, not how deep.
NESTING = ("body[]", "then[]", "else[]")
NESTED = "<nested>[]"

# The door inventory: every coordinate slot on an OwnIR document, as the tail
# of a census path. A document can sit at a file root (`*.facts.json`), or
# nested inside a ledger (`cases[].document`) or a reproduction artifact
# (`input.document`), so slots are matched on the tail rather than the whole
# path — which is also what makes an unreachable slot detectable.
SLOTS: tuple[tuple[str, str], ...] = (
    ("components[].subscriptions[].line", "line"),
    ("components[].subscriptions[].column", "column"),
    ("services[].line", "line"),
    ("services[].ctor_line", "line"),
    ("services[].root_resolve_sites[].line", "line"),
    ("services[].scope_cache_sites[].line", "line"),
    ("effects[].line", "line"),
    ("effects[].bindings[].line", "line"),
    ("functions[].params[].line", "line"),
    ("functions[].params[].column", "column"),
    (f"functions[].{NESTED}.line", "line"),
    (f"functions[].{NESTED}.column", "column"),
    ("protocol_functions[].events[].line", "line"),
    (f"protocol_functions[].events[].{NESTED}.line", "line"),
)


@dataclass(frozen=True)
class Row:
    """One census row: a family, a slot path, a value class and how many."""

    family: str
    path: str
    kind: str
    value_class: str
    door: bool
    count: int
    files: int
    examples: tuple[str, ...]


@dataclass(frozen=True)
class CoordinateCensus:
    files: int
    coordinates: int
    by_class: tuple[tuple[str, int], ...]
    door_by_class: tuple[tuple[str, int], ...]
    rows: tuple[Row, ...]
    unreachable_slots: tuple[str, ...]


class CoordinateCensusError(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def classify(kind: str, value: Any) -> str:
    """The value's class. `kind` is `line` or `column`; they share every
    non-integer class and differ only in which integers are in the domain."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if not isinstance(value, int):
        return "other"
    # Representability first, exactly as the door orders it: a value with no
    # integer form the contract can hold cannot go on to violate a rule about
    # what that form means.
    if not INT64_MIN <= value <= INT64_MAX:
        return "outside-int64"
    if kind == "column":
        if value < COLUMN_MIN:
            return "below-1"
        return "in-domain" if value <= COLUMN_MAX else "above-int32"
    if value == LINE_MIN:
        return "zero"
    if value < LINE_MIN:
        return "negative"
    return "in-domain" if value <= LINE_MAX else "above-int32"


def _collapse(path: str) -> str:
    out: list[str] = []
    for segment in path.split("."):
        if segment in NESTING:
            if out and out[-1] == NESTED:
                continue
            out.append(NESTED)
        else:
            out.append(segment)
    return ".".join(out)


def _walk(node: Any, path: str, out: list[tuple[str, str, Any]]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}" if path else key
            if key in COORD_KEYS and not isinstance(value, (dict, list)):
                out.append((child, "column" if key == "column" else "line", value))
            else:
                _walk(value, child, out)
    elif isinstance(node, list):
        for value in node:
            _walk(value, f"{path}[]", out)


def _is_door_slot(path: str, kind: str) -> bool:
    return any(path.endswith(slot) and slot_kind == kind for slot, slot_kind in SLOTS)


def compute_coordinate_census() -> CoordinateCensus:
    """Walk the fixture tree once and classify every coordinate it holds."""
    problems: list[str] = []
    counts: dict[tuple[str, str, str, str], int] = {}
    files_per_row: dict[tuple[str, str, str, str], set[str]] = {}
    examples: dict[tuple[str, str, str, str], set[str]] = {}
    reached: set[str] = set()
    scanned = 0
    for directory, subdirs, names in os.walk(FIXTURES):
        subdirs.sort()
        family = os.path.relpath(directory, FIXTURES).replace(os.sep, "/")
        family = "(root)" if family == "." else family
        for name in sorted(names):
            if not name.endswith(".json"):
                continue
            path = os.path.join(directory, name)
            scanned += 1
            try:
                with open(path, encoding="utf-8") as f:
                    document = json.load(f)
            except (OSError, ValueError) as e:
                problems.append(f"{os.path.relpath(path, HERE)}: unreadable: {e}")
                continue
            found: list[tuple[str, str, Any]] = []
            _walk(document, "", found)
            for raw, kind, value in found:
                slot = _collapse(raw)
                door = _is_door_slot(slot, kind)
                if door:
                    reached.add(slot)
                key = (family, slot, kind, classify(kind, value))
                counts[key] = counts.get(key, 0) + 1
                files_per_row.setdefault(key, set()).add(name)
                if key[3] not in ("in-domain", "null", "zero"):
                    examples.setdefault(key, set()).add(repr(value))
    if problems:
        raise CoordinateCensusError(problems)
    rows = tuple(
        Row(
            family=family,
            path=slot,
            kind=kind,
            value_class=value_class,
            door=_is_door_slot(slot, kind),
            count=count,
            files=len(files_per_row[(family, slot, kind, value_class)]),
            examples=tuple(sorted(examples.get((family, slot, kind, value_class), set()))),
        )
        for (family, slot, kind, value_class), count in sorted(counts.items())
    )
    by_class: dict[str, int] = {}
    door_by_class: dict[str, int] = {}
    for row in rows:
        by_class[row.value_class] = by_class.get(row.value_class, 0) + row.count
        if row.door:
            door_by_class[row.value_class] = door_by_class.get(row.value_class, 0) + row.count
    # A declared slot no file reaches is a phantom: the inventory would go on
    # claiming coverage it does not have, which is the failure mode the
    # schema's binding map is asserted AS a map to avoid.
    unreachable = tuple(sorted({slot for slot, _ in SLOTS} - reached))
    return CoordinateCensus(
        files=scanned,
        coordinates=sum(by_class.values()),
        by_class=tuple(sorted(by_class.items())),
        door_by_class=tuple(sorted(door_by_class.items())),
        rows=rows,
        unreachable_slots=unreachable,
    )
