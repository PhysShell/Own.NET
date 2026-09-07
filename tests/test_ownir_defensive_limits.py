#!/usr/bin/env python3
"""The two defensive limits on externally supplied OwnIR (spec/OwnIR.md §4.2).

`OwnIR` is a file some frontend wrote. Two of its shapes had no bound at all,
and the reference accepted both because *Python* has no bound: integers are
arbitrary-precision, and recursion is limited only by the interpreter's stack.

That is not generosity, it is an accident of the reference's implementation
leaking into the contract. It surfaced as a measured Python-accept/Rust-reject
pair in #259 cp1 — the Rust port refusing documents the reference took — and the
honest reading of that is not "the port is over-strict". It is that the
vocabulary was only implementable in a language with bignums and a deep stack.

So the fix is Python-first, which is the migration's standing rule: a
Rust/Python divergence is a Rust bug **unless behaviour changes in a separate
Python-first PR**. This is that PR.

## What is asserted here, and why the boundary and not just the failure

Each limit is pinned at three points: below, exactly at, and one past. A test
that only checks "something far too big is rejected" cannot tell a correct limit
from one that is off by one — and the nesting limit *was* off by one when first
written, because `_check_flow_coordinates` probes every op for `then`/`else`/`body`
whether or not it has them, so the absent ones were counting as levels. At-limit
rejected. Only the boundary case could catch that.

## Why 32

Measured from both ends rather than picked:

* the deepest nesting in any `OwnIR` fixture in this repository is 3;
* a JSON parser with the widespread 128-level recursion cap stops accepting
  these documents at 62 levels, since each `if` costs two JSON levels.

Run:  python tests/test_ownir_defensive_limits.py
      python tests/run_tests.py                    (in the suite)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from coordinate_census import classify, door_coordinates

from ownlang.obligations import (
    COLUMN_MAX,
    COLUMN_MIN,
    INT64_MAX,
    INT64_MIN,
    LINE_MAX,
    LINE_MIN,
    MAX_NESTING_DEPTH,
)
from ownlang.ownir import OwnIRError, check_facts, load


def _load(document: Any) -> str | None:
    """Run the strict door; return None on accept, the message on reject."""
    directory = tempfile.mkdtemp()
    path = os.path.join(directory, "facts.ownir.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(document, f)
        try:
            load(path)
            return None
        except OwnIRError as e:
            return str(e)
    finally:
        if os.path.exists(path):
            os.unlink(path)
        os.rmdir(directory)


def _svc(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"name": "S", "lifetime": "singleton"}
    base.update(kw)
    return base


def _body(depth: int, key: str = "then") -> dict[str, Any]:
    """A function flow body nested `depth` levels through `key`."""
    node: dict[str, Any] = {"op": "acquire", "column": 1}
    for _ in range(depth):
        node = {"op": "if" if key != "body" else "while", key: [node]}
    return {"ownir_version": 0, "functions": [{"body": [node]}]}


def _events(depth: int, key: str = "then") -> dict[str, Any]:
    """A protocol event tree nested `depth` levels through `key`."""
    node: dict[str, Any] = {"ev": "return", "line": 1}
    for _ in range(depth):
        node = {"ev": "if" if key != "body" else "while", "line": 1, key: [node]}
    return {"ownir_version": 0,
            "protocol_functions": [{"name": "M", "events": [node]}]}


# Every path a source coordinate travels. Named as (label, builder) so a new
# coordinate field that skips the check shows up as a missing row rather than
# as nothing at all.
LINE_PATHS: list[tuple[str, Any]] = [
    ("services[].line", lambda v: {"services": [_svc(line=v)]}),
    ("services[].ctor_line", lambda v: {"services": [_svc(ctor_line=v)]}),
    ("services[].root_resolve_sites[].line",
     lambda v: {"services": [_svc(root_resolve_sites=[{"line": v}])]}),
    ("services[].scope_cache_sites[].line",
     lambda v: {"services": [_svc(scope_cache_sites=[{"line": v}])]}),
    ("effects[].line", lambda v: {"effects": [{"line": v}]}),
    ("effects[].bindings[].line",
     lambda v: {"effects": [{"bindings": [{"line": v}]}]}),
    ("functions[].params[].line",
     lambda v: {"functions": [{"params": [{"name": "p", "line": v}]}]}),
    ("protocol_functions[].events[].line",
     lambda v: {"protocol_functions": [
         {"name": "M", "events": [{"ev": "return", "line": v}]}]}),
    # The two fields §4.2 used to record as validated NOWHERE. They are here
    # rather than in a block of their own because the point of #259's final
    # acceptance is that they are no longer special: one domain, one table.
    ("components[].subscriptions[].line",
     lambda v: {"components": [{"subscriptions": [{"line": v}]}]}),
    ("functions[].body[].line",
     lambda v: {"functions": [{"body": [{"op": "acquire", "line": v}]}]}),
    # …and at every nesting shape, because `then`/`else`/`body` are three
    # separate recursive call sites: a check added to one of them would pass a
    # top-level-only test, which is the same trap the nesting limit records.
    ("functions[].body[].then[].line",
     lambda v: {"functions": [{"body": [
         {"op": "if", "then": [{"op": "acquire", "line": v}]}]}]}),
    ("functions[].body[].else[].line",
     lambda v: {"functions": [{"body": [
         {"op": "if", "else": [{"op": "acquire", "line": v}]}]}]}),
    ("functions[].body[].body[].line",
     lambda v: {"functions": [{"body": [
         {"op": "while", "body": [{"op": "acquire", "line": v}]}]}]}),
]

# The same paths, for the TYPE rule. Every line field rejects a non-integer;
# the two newly validated ones had no type check at all before this change, so
# `{"line": "x"}` and `{"line": true}` were accepted documents.
TYPE_REJECTED = ("x", True, None, 1.5)

COLUMN_PATHS: list[tuple[str, Any]] = [
    ("subscriptions[].column",
     lambda v: {"components": [{"subscriptions": [{"column": v}]}]}),
    ("functions[].params[].column",
     lambda v: {"functions": [{"params": [{"name": "p", "column": v}]}]}),
    ("functions[].body[].column",
     lambda v: {"functions": [{"body": [{"op": "a", "column": v}]}]}),
]


# The spec's numbers, written as LITERALS.
#
# The rest of this file imports the constants from the module, which means it
# moves whenever they do — so on its own it can prove the limits are enforced
# consistently and cannot prove they are the *right* limits. Measured: widening
# `INT64_MAX` to `2**64 - 1` SURVIVED mutation until these three lines existed,
# because every boundary case simply followed the constant.
#
# A parity ledger caught the same class of error one layer up in #259 cp1. It is
# worth stating plainly: a test written in terms of the value under test asserts
# self-consistency, not correctness.
SPEC_INT64_MIN = -9223372036854775808
SPEC_INT64_MAX = 9223372036854775807
SPEC_LINE_MIN = 0
SPEC_LINE_MAX = 2147483647
SPEC_COLUMN_MIN = 1
SPEC_COLUMN_MAX = 2147483647
SPEC_MAX_NESTING_DEPTH = 32


def _fail(message: str, check: str = "defensive-limits") -> int:
    """One failure, named by the CHECK it violated.

    The bracketed name is what a mutation campaign reads (`python-fail` in
    `scripts/mutate_campaign.py`), so a mutation's expected catcher can be the
    rule it attacks rather than "this file exited non-zero" — which would make
    every mutation in this file look identically caught."""
    print(f"FAIL[{check}]: {message}")
    return 1


def run() -> int:
    failures = 0

    # The constants match spec/OwnIR.md §4.2, checked against literals so that
    # changing a limit fails here rather than silently redefining every
    # boundary case below.
    for name, actual, expected in (
        ("INT64_MIN", INT64_MIN, SPEC_INT64_MIN),
        ("INT64_MAX", INT64_MAX, SPEC_INT64_MAX),
        ("LINE_MIN", LINE_MIN, SPEC_LINE_MIN),
        ("LINE_MAX", LINE_MAX, SPEC_LINE_MAX),
        ("COLUMN_MIN", COLUMN_MIN, SPEC_COLUMN_MIN),
        ("COLUMN_MAX", COLUMN_MAX, SPEC_COLUMN_MAX),
        ("MAX_NESTING_DEPTH", MAX_NESTING_DEPTH, SPEC_MAX_NESTING_DEPTH),
    ):
        if actual != expected:
            failures += _fail(
                f"{name} is {actual}, spec/OwnIR.md §4.2 says {expected}. "
                f"Changing a defensive limit is a contract change: update the "
                f"spec, this literal, and the Rust side together", check="spec-literals")

    # ---- the JSON schema carries the same numbers -------------------------
    # `spec/ownir.schema.json` is the contract a NON-Python consumer validates
    # against. If the bounds live only in `load()`, a producer can be schema-
    # valid and still refused at the door — which is the same cross-consumer
    # mismatch this change exists to remove, one layer out.
    schema_path = os.path.join(
        os.path.dirname(__file__), "..", "spec", "ownir.schema.json")
    with open(schema_path, encoding="utf-8") as f:
        defs = json.load(f)["$defs"]
    for name, key, expected in (
        ("sourceLine", "minimum", SPEC_LINE_MIN),
        ("sourceLine", "maximum", SPEC_LINE_MAX),
        ("sourceColumn", "minimum", SPEC_COLUMN_MIN),
        ("sourceColumn", "maximum", SPEC_COLUMN_MAX),
        # `column: null` is accepted by `load()`, so the schema must permit it.
        # `minimum`/`maximum` only constrain numbers, so the bounds above still
        # apply to real values.
        ("sourceColumn", "type", ["integer", "null"]),
    ):
        actual = defs.get(name, {}).get(key)
        if actual != expected:
            failures += _fail(
                f"spec/ownir.schema.json $defs.{name}.{key} is {actual!r}, "
                f"expected {expected!r} — the schema and `load()` must state the "
                f"same bound or a producer can satisfy one and fail the other",
                check="schema-numbers")

    # …and the schema binds `sourceLine` on EXACTLY the paths `load()` checks.
    #
    # Both directions are defects and both were shipped in the first attempt at
    # this file. Binding a path the loader ignores makes a producer schema-
    # invalid while the door accepts it; leaving a checked path unbound makes it
    # schema-valid while the door refuses it. A blanket search-and-replace over
    # `"line"` did the first to `resourceRecord` and `flowOp` — the two paths
    # §4.2 then documented as unvalidated — and the second to `ctor_line`, whose
    # key simply differs.
    #
    # So the map is asserted as a map, not spot-checked.
    #
    # `UNBOUND` is EMPTY since #259's final acceptance: §4.2's exception is
    # closed and every coordinate-bearing path is checked by `load()`. The
    # machinery stays rather than being deleted with its last entry, because
    # what it enforces is that a path is *classified* — the next unbound path
    # somebody adds must be declared here, not discovered by nobody.
    BOUND = {"service": ["line", "ctor_line"], "site": ["line"],
             "effect": ["line"], "binding": ["line"], "param": ["line"],
             "protocolEvent": ["line"], "resourceRecord": ["line"],
             "flowOp": ["line"]}
    UNBOUND: dict[str, list[str]] = {}

    # …and the map is CLOSED over the schema, which the per-member checks below
    # cannot establish on their own.
    #
    # They walk the defs the map already names, so a new `$def` carrying a
    # coordinate — added next year by someone who does not know this file
    # exists — is absent from both sides and checked by neither. The map would
    # go on passing while covering less of the schema, which is the same defect
    # as the two mutation survivors that produced this file's current shape: an
    # assertion that faithfully proves the completeness of a list, using the
    # list.
    #
    # So the classified set is compared with the DISCOVERED one. Anything
    # carrying `line` or `ctor_line` and belonging to neither side is RED, and
    # the fix is to decide which side it is on rather than to widen this.
    def _coordinate_defs(node: Any, found: set[str], name: str = "") -> set[str]:
        if isinstance(node, dict):
            props = node.get("properties")
            if isinstance(props, dict) and ({"line", "ctor_line"} & props.keys()):
                found.add(name)
            for value in node.values():
                _coordinate_defs(value, found, name)
        elif isinstance(node, list):
            for value in node:
                _coordinate_defs(value, found, name)
        return found

    discovered = set()
    for def_name, subschema in defs.items():
        _coordinate_defs(subschema, discovered, def_name)
    classified = set(BOUND) | set(UNBOUND)
    if discovered != classified:
        unclassified = sorted(discovered - classified)
        phantom = sorted(classified - discovered)
        if unclassified:
            failures += _fail(
                f"$defs {unclassified} carry a source coordinate and appear in "
                f"neither BOUND nor UNBOUND — every coordinate-bearing def must "
                f"be classified, because an unclassified one is checked by "
                f"nothing at all", check="schema-binding")
        if phantom:
            failures += _fail(
                f"the binding map names {phantom}, which no longer carry a "
                f"coordinate — a map entry pointing at nothing has stopped "
                f"being evidence", check="schema-binding")

    # Whole subschemas, not just their `$ref`. Asserting only "the ref is not
    # sourceLine" left an unbound path free to be tightened another way —
    # measured: pointing `flowOp.line` at `sourceColumn`, or giving it an inline
    # `maximum`, both SURVIVED until this kept the object.
    def _subschemas(node: Any, key: str, out: list[Any]) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k == key and isinstance(v, dict):
                    out.append(v)
                else:
                    _subschemas(v, key, out)
        elif isinstance(node, list):
            for v in node:
                _subschemas(v, key, out)

    # Anything that would make an UNBOUND path narrower than `load()`.
    NARROWING = ("$ref", "minimum", "maximum", "exclusiveMinimum",
                 "exclusiveMaximum", "enum", "const", "multipleOf")

    for group, expect_bound in ((BOUND, True), (UNBOUND, False)):
        for def_name, keys in group.items():
            for key in keys:
                found: list[Any] = []
                _subschemas(defs.get(def_name, {}), key, found)
                if not found:
                    failures += _fail(
                        f"$defs.{def_name} has no {key!r} — the binding map is "
                        f"stale, which means it is no longer evidence", check="schema-binding")
                for sub in found:
                    if expect_bound:
                        if sub.get("$ref") != "#/$defs/sourceLine":
                            failures += _fail(
                                f"$defs.{def_name}.{key} is {sub!r}, expected "
                                f"$ref sourceLine — `load()` checks this path, "
                                f"so a schema-valid document must not be able "
                                f"to fail at the door", check="schema-binding")
                        continue
                    narrowed = [k for k in NARROWING if k in sub]
                    if narrowed or sub.get("type") != "integer":
                        failures += _fail(
                            f"$defs.{def_name}.{key} is {sub!r}, expected a "
                            f"plain integer with no {'/'.join(NARROWING[:3])}… "
                            f"— `load()` does NOT check this path (§4.2), so "
                            f"any narrowing makes a document schema-invalid "
                            f"that the door accepts", check="schema-binding")

    # ---- line: the DOMAIN, pinned at both ends and one step outside each --
    #
    # Two axes, in the order the door checks them, so neither can silently
    # absorb the other: a value with no representable signed-64 form reports
    # the FORM rule, and a representable value outside `[0, 2^31-1]` reports
    # the DOMAIN rule. `i64::MAX` is the control that keeps them apart — it was
    # an accepted line until #259's final acceptance, and it is now a domain
    # rejection rather than a form one.
    for label, build in LINE_PATHS:
        for value, expected in ((LINE_MIN, None), (1, None), (LINE_MAX, None),
                                (LINE_MIN - 1, "source line in"),
                                (LINE_MAX + 1, "source line in"),
                                (INT64_MIN, "source line in"),
                                (INT64_MAX, "source line in"),
                                (INT64_MIN - 1, "signed 64-bit"),
                                (INT64_MAX + 1, "signed 64-bit")):
            err = _load(build(value))
            if expected is None and err is not None:
                failures += _fail(f"{label}: {value} rejected — {err}", check="line-domain")
            elif expected is not None and err is None:
                failures += _fail(f"{label}: {value} accepted, expected reject",
                                  check="line-domain")
            elif expected is not None and expected not in (err or ""):
                failures += _fail(
                    f"{label}: {value} rejected for the wrong reason — "
                    f"expected the {expected!r} rule, got {err}", check="line-domain")

    # ---- line: the TYPE rule, on every path -------------------------------
    #
    # Only the rejection is asserted, not the message. The reference folds a
    # site record's whole check into one `all(...)`, so a mistyped site line
    # reports the record's shape rather than the field's — one violation, one
    # message, and the cp1 ledger is where the CATEGORY of each is pinned.
    for label, build in LINE_PATHS:
        for value in TYPE_REJECTED:
            if _load(build(value)) is None:
                failures += _fail(
                    f"{label}: {value!r} accepted — a line must be an integer", check="line-type")

    # ---- column: 1-based below, the domain above --------------------------
    for label, build in COLUMN_PATHS:
        for value, expected in ((COLUMN_MIN, None), (COLUMN_MAX, None),
                                (COLUMN_MAX + 1, "source column in"),
                                (INT64_MAX, "source column in"),
                                (INT64_MAX + 1, "signed 64-bit")):
            err = _load(build(value))
            if expected is None and err is not None:
                failures += _fail(f"{label}: {value} rejected — {err}", check="column-domain")
            elif expected is not None and err is None:
                failures += _fail(f"{label}: {value} accepted, expected reject",
                                  check="column-domain")
            elif expected is not None and expected not in (err or ""):
                failures += _fail(
                    f"{label}: {value} rejected for the wrong reason — "
                    f"expected the {expected!r} rule, got {err}", check="column-domain")
        # The 1-based rule still fires FIRST for every low column, so neither
        # new bound can have replaced it — including for a value that is also
        # outside the representable form, where the order is what decides which
        # rule the reader is told about.
        for low in (0, -1, INT64_MIN, INT64_MIN - 1):
            if "1-based" not in (_load(build(low)) or ""):
                failures += _fail(
                    f"{label}: {low} no longer reports the 1-based rule", check="column-domain")

    # ---- nesting: below, exactly at, one past — for both trees and both
    # recursive keys, because `then`/`else`/`body` are three separate call
    # sites and a limit added to one of them would pass a `then`-only test.
    for label, build in (("functions[].body", _body),
                         ("protocol_functions[].events", _events)):
        for key in ("then", "else", "body"):
            for depth, expect_reject in ((MAX_NESTING_DEPTH - 1, False),
                                         (MAX_NESTING_DEPTH, False),
                                         (MAX_NESTING_DEPTH + 1, True)):
                err = _load(build(depth, key))
                if expect_reject and err is None:
                    failures += _fail(
                        f"{label} via {key!r}: depth {depth} accepted, "
                        f"expected reject (the limit is {MAX_NESTING_DEPTH})", check="nesting")
                elif not expect_reject and err is not None:
                    failures += _fail(
                        f"{label} via {key!r}: depth {depth} rejected — {err}", check="nesting")
                elif expect_reject and "nested deeper" not in (err or ""):
                    failures += _fail(
                        f"{label} via {key!r}: depth {depth} rejected for the "
                        f"wrong reason — {err}", check="nesting")

    # ---- the tolerances the limits must NOT have tightened ----------------
    # A non-list body is skipped, not rejected; the reference returns early.
    # Bounding depth is the kind of change that quietly turns that into a
    # rejection, so it is asserted rather than assumed.
    for label, document in (
        ("non-list body", {"ownir_version": 0, "functions": [{"body": 7}]}),
        ("body of scalars",
         {"ownir_version": 0, "functions": [{"body": [1, "x", None]}]}),
        ("absent sections", {"ownir_version": 0}),
        ("null column",
         {"ownir_version": 0,
          "components": [{"subscriptions": [{"column": None}]}]}),
    ):
        err = _load(document)
        if err is not None:
            failures += _fail(f"{label} must still be accepted — {err}", check="tolerances")

    # ---- the TOLERANT door degrades; it never raises and never clamps -----
    #
    # `check_facts()` is the door tests and embedders take, and it may be
    # handed facts `load()` never saw. An out-of-domain line there reads as
    # `0` — the value an absent line already reads as — and the finding is
    # still reported at its file. The clamp controls are the point: `2^31`
    # must not become `2^31 - 1` and `-1` must not become `1`, because a
    # clamped anchor points at a REAL line the producer did not mean.
    def _sub(line: Any) -> dict[str, Any]:
        return {"ownir_version": 0, "module": "X",
                "components": [{"name": "C", "file": "C.cs", "subscriptions": [
                    {"event": "e", "handler": "h", "line": line,
                     "source": "static"}]}]}

    def _acquire(line: Any) -> dict[str, Any]:
        return {"ownir_version": 0, "module": "X", "functions": [
            {"name": "F", "file": "F.cs",
             "body": [{"op": "acquire", "var": "x", "line": line}]}]}

    def _event(line: Any) -> dict[str, Any]:
        return {"ownir_version": 0, "module": "X",
                "protocols": [{"name": "P",
                               "opens": {"kind": "assign", "target": "f",
                                         "value": True},
                               "closes": {"kind": "assign", "target": "f",
                                          "value": False},
                               "barriers": [{"kind": "call", "callee": "B"}]}],
                "protocol_functions": [{"name": "M", "file": "M.cs", "events": [
                    {"ev": "assign", "target": "f", "value": True, "line": line},
                    {"ev": "call", "callee": "B", "line": 9}]}]}

    # Out-of-DOMAIN values degrade on every path…
    OUT_OF_DOMAIN = (-1, LINE_MIN - 1, LINE_MAX + 1, 2 ** 31, INT64_MAX)
    # …while a value with no integer form at all degrades on the two paths
    # whose reader is `_as_line`, and SKIPS the entry on the protocol path.
    # That asymmetry is the obligation family's own tolerant rule ("a
    # malformed entry is skipped whole", cp4b) and is deliberately untouched:
    # type and representability are grammar, the domain is the door's.
    for label, build_facts, code in (("subscription", _sub, "OWN001"),
                                     ("flow acquire", _acquire, "OWN001"),
                                     ("protocol event", _event, "OBL003")):
        values = OUT_OF_DOMAIN if label == "protocol event" else (
            *OUT_OF_DOMAIN, "x", True, None)
        for value in values:
            anchors = [(f.code, f.line) for f in check_facts(build_facts(value))
                       if f.code == code]
            if anchors != [(code, 0)]:
                failures += _fail(
                    f"tolerant {label} line {value!r}: expected "
                    f"[({code}, 0)] — degrade to absent, never clamp — got "
                    f"{anchors}", check="tolerant-degrade")
    for value in ("x", True, None, INT64_MAX + 1):
        if [f for f in check_facts(_event(value)) if f.code == "OBL003"]:
            failures += _fail(
                f"tolerant protocol event line {value!r}: the grammar rejects "
                f"it, so the ENTRY is skipped whole (cp4b) — a finding here "
                f"means the domain degrade swallowed a grammar rule", check="tolerant-degrade")
        # …and a line INSIDE the domain is preserved exactly, so the degrade
        # cannot have swallowed the ordinary path.
        for value in (1, LINE_MAX):
            anchors = [(f.code, f.line) for f in check_facts(build_facts(value))
                       if f.code == code]
            if anchors != [(code, value)]:
                failures += _fail(
                    f"tolerant {label} line {value}: in-domain lines must be "
                    f"preserved, got {anchors}", check="tolerant-degrade")

    # …and the COLUMN degrades the same way, on its own domain. Its reader is
    # `_as_col`, which the four verdict_boundary_* controls never reach — the
    # only thing that pins the tolerant column bound is right here and the one
    # synthetic Layer 3 case written for it.
    def _sub_col(column: Any) -> dict[str, Any]:
        return {"ownir_version": 0, "module": "X",
                "components": [{"name": "C", "file": "C.cs", "subscriptions": [
                    {"event": "e", "handler": "h", "line": 7, "column": column,
                     "source": "static"}]}]}

    for value, want in ((COLUMN_MIN, COLUMN_MIN), (COLUMN_MAX, COLUMN_MAX),
                        (COLUMN_MAX + 1, None), (INT64_MAX, None), (0, None),
                        (-1, None), (True, None), ("x", None), (None, None)):
        cols = [f.column for f in check_facts(_sub_col(value)) if f.code == "OWN001"]
        if cols != [want]:
            failures += _fail(
                f"tolerant column {value!r}: expected [{want!r}] — a column "
                f"outside the domain is ABSENT, never clamped — got {cols}",
                check="tolerant-degrade")

    # ---- and the strict door never REACHES the degrade --------------------
    #
    # The two-doors contract only holds if the strict door's output is a
    # subset of the tolerant door's input domain: a document `load()` accepts
    # must carry no out-of-domain coordinate at all, or `_as_line` would be
    # silently rewriting validated facts. That is asserted over every document
    # the #259 cp1 ledger records as ACCEPTED, rather than stated in prose —
    # the ledger is the widest set of accepted documents in the tree, and it
    # is derived from the reference itself.
    ledger_path = os.path.join(os.path.dirname(__file__), "fixtures",
                               "ownir_validation.json")
    with open(ledger_path, encoding="utf-8") as f:
        ledger = json.load(f)
    accepted = 0
    for case in ledger["cases"]:
        if case.get("verdict") != "accept" or case.get("raw"):
            continue
        accepted += 1
        for slot, kind, value in door_coordinates(case["document"]):
            if classify(kind, value) not in ("in-domain", "zero", "null"):
                failures += _fail(
                    f"cp1 control {case['name']!r} is ACCEPTED by the strict "
                    f"door and carries {slot} = {value!r}, which the tolerant "
                    f"door would degrade — the strict door must never reach "
                    f"the degrade (spec/OwnIR.md §4.2)", check="strict-subset")
    if not accepted:
        failures += _fail(
            "no accepted cp1 control was read — the subset assertion above "
            "passed over an empty set, which is not evidence", check="strict-subset")

    if failures:
        return 1
    print(
        f"ownir defensive limits OK: lines in [{LINE_MIN}, {LINE_MAX}] and "
        f"columns in [{COLUMN_MIN}, {COLUMN_MAX}] inside the signed-64 form, "
        f"over {len(LINE_PATHS)} line paths and {len(COLUMN_PATHS)} column "
        f"paths; nesting <= {MAX_NESTING_DEPTH} over 2 trees x 3 keys, each "
        f"pinned at limit and limit+1; the tolerant door degrades on 3 paths "
        f"and the strict door reaches it on none of {accepted} accepted cp1 "
        f"controls"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
