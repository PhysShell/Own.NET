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
written, because `_check_flow_columns` probes every op for `then`/`else`/`body`
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

from ownlang.obligations import INT64_MAX, INT64_MIN, MAX_NESTING_DEPTH
from ownlang.ownir import OwnIRError, load


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
]

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
SPEC_MAX_NESTING_DEPTH = 32


def _fail(message: str) -> int:
    print(f"FAIL: {message}")
    return 1


def run() -> int:
    failures = 0

    # The constants match spec/OwnIR.md §4.2, checked against literals so that
    # changing a limit fails here rather than silently redefining every
    # boundary case below.
    for name, actual, expected in (
        ("INT64_MIN", INT64_MIN, SPEC_INT64_MIN),
        ("INT64_MAX", INT64_MAX, SPEC_INT64_MAX),
        ("MAX_NESTING_DEPTH", MAX_NESTING_DEPTH, SPEC_MAX_NESTING_DEPTH),
    ):
        if actual != expected:
            failures += _fail(
                f"{name} is {actual}, spec/OwnIR.md §4.2 says {expected}. "
                f"Changing a defensive limit is a contract change: update the "
                f"spec, this literal, and the Rust side together")

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
        ("sourceLine", "minimum", SPEC_INT64_MIN),
        ("sourceLine", "maximum", SPEC_INT64_MAX),
        ("sourceColumn", "minimum", 1),
        ("sourceColumn", "maximum", SPEC_INT64_MAX),
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
                f"same bound or a producer can satisfy one and fail the other")

    # …and the schema binds `sourceLine` on EXACTLY the paths `load()` checks.
    #
    # Both directions are defects and both were shipped in the first attempt at
    # this file. Binding a path the loader ignores makes a producer schema-
    # invalid while the door accepts it; leaving a checked path unbound makes it
    # schema-valid while the door refuses it. A blanket search-and-replace over
    # `"line"` did the first to `resourceRecord` and `flowOp` — the two paths
    # §4.2 documents as unvalidated — and the second to `ctor_line`, whose key
    # simply differs.
    #
    # So the map is asserted as a map, not spot-checked.
    BOUND = {"service": ["line", "ctor_line"], "site": ["line"],
             "effect": ["line"], "binding": ["line"], "param": ["line"],
             "protocolEvent": ["line"]}
    UNBOUND = {"resourceRecord": ["line"], "flowOp": ["line"]}

    def _line_refs(node: Any, key: str, out: list[Any]) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k == key and isinstance(v, dict):
                    out.append(v.get("$ref") or v.get("type"))
                else:
                    _line_refs(v, key, out)
        elif isinstance(node, list):
            for v in node:
                _line_refs(v, key, out)

    for group, expect_bound in ((BOUND, True), (UNBOUND, False)):
        for def_name, keys in group.items():
            for key in keys:
                found: list[Any] = []
                _line_refs(defs.get(def_name, {}), key, found)
                if not found:
                    failures += _fail(
                        f"$defs.{def_name} has no {key!r} — the binding map is "
                        f"stale, which means it is no longer evidence")
                for ref in found:
                    is_bound = ref == "#/$defs/sourceLine"
                    if is_bound != expect_bound:
                        want = ("$ref sourceLine" if expect_bound
                                else "an unrestricted integer")
                        why = ("`load()` checks this path"
                               if expect_bound else
                               "`load()` does NOT check this path (§4.2)")
                        failures += _fail(
                            f"$defs.{def_name}.{key} is {ref!r}, expected "
                            f"{want} — {why}")

    # ---- line: the full signed-64 range, and one step outside each end -----
    for label, build in LINE_PATHS:
        for value, expect_reject in ((INT64_MIN, False), (0, False),
                                     (INT64_MAX, False),
                                     (INT64_MIN - 1, True), (INT64_MAX + 1, True)):
            err = _load(build(value))
            if expect_reject and err is None:
                failures += _fail(f"{label}: {value} accepted, expected reject")
            elif not expect_reject and err is not None:
                failures += _fail(f"{label}: {value} rejected — {err}")
            elif expect_reject and "signed 64-bit" not in (err or ""):
                failures += _fail(
                    f"{label}: {value} rejected for the wrong reason — {err}")

    # ---- column: 1-based below, and the same upper bound ------------------
    for label, build in COLUMN_PATHS:
        for value, expect_reject in ((1, False), (INT64_MAX, False),
                                     (INT64_MAX + 1, True)):
            err = _load(build(value))
            if expect_reject and err is None:
                failures += _fail(f"{label}: {value} accepted, expected reject")
            elif not expect_reject and err is not None:
                failures += _fail(f"{label}: {value} rejected — {err}")
        # The 1-based rule still fires first for a low column, so the new upper
        # bound cannot have replaced it.
        if "1-based" not in (_load(build(0)) or ""):
            failures += _fail(f"{label}: 0 no longer reports the 1-based rule")

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
                        f"expected reject (the limit is {MAX_NESTING_DEPTH})")
                elif not expect_reject and err is not None:
                    failures += _fail(
                        f"{label} via {key!r}: depth {depth} rejected — {err}")
                elif expect_reject and "nested deeper" not in (err or ""):
                    failures += _fail(
                        f"{label} via {key!r}: depth {depth} rejected for the "
                        f"wrong reason — {err}")

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
            failures += _fail(f"{label} must still be accepted — {err}")

    if failures:
        return 1
    print(
        f"ownir defensive limits OK: coordinates in "
        f"[{INT64_MIN}, {INT64_MAX}] over {len(LINE_PATHS)} line paths and "
        f"{len(COLUMN_PATHS)} column paths; nesting <= {MAX_NESTING_DEPTH} "
        f"over 2 trees x 3 keys, each pinned at limit and limit+1"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
