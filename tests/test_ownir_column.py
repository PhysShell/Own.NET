#!/usr/bin/env python3
"""
The physical-anchor column contract (`column` fact -> `Finding.column` -> SARIF
`region.startColumn`).

These are the SHORT checks — the ones that belong in every PR's CI, run on tiny
synthetic facts in milliseconds. The long, real-corpus evidence is a separate
contour (OwnAudit's `corpusdiff`); this file pins the contract that makes that
comparison meaningful in the first place.

FOUR CONTRACT QUESTIONS, PLUS THE ONE THAT IS EASY TO GET WRONG
---------------------------------------------------------------
  1. An OLD fact (no `column`) is still accepted, and its SARIF carries NO
     `startColumn`. Additive means additive: a producer built before this slice
     keeps working and keeps producing the anchor it always did.
  2. A fact WITH a column carries it onto `Finding.column` and out as
     `region.startColumn`.
  3. An INVALID column FAILS LOUD at `load()` — 0, negative, boolean, string,
     float. The asymmetry against `line` (which degrades to 0) is deliberate: an
     absent column is a producer honestly reporting less, a coerced one is a
     coordinate the analysis never computed sitting in the anchor a consumer keys
     identity on. On the TOLERANT door (`check_facts` on unvalidated facts) it
     degrades to None instead, exactly like `line` degrades to 0.
  4. The old and new producers over ONE fixture agree on every finding and on
     every pattern-level field. Only the physical anchor moves. This is the
     fixture-scale version of what the corpus differential asserts over a real
     tree, and if it fails here the corpus run has nothing to measure.
  5. `_caret_col` IS NOWHERE NEAR THIS. `diagnostics.Diagnostic._caret_col`
     recovers a column for a rendered `^` by pulling a name out of the message
     and searching the source line, falling back to the indentation. It is a
     presentation heuristic and it must never reach a fact, a `Finding`, or SARIF
     — a guessed coordinate that looks measured is worse than an absent one,
     because absence is visible in a coverage ledger and a guess is not. Pinned
     two ways: behaviourally (no column is invented) and structurally (the
     modules on this path do not reference it).

Run:  python tests/test_ownir_column.py
      python tests/run_tests.py     (as part of the suite)
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.diagnostics import Diagnostic, Severity
from ownlang.ownir import (
    OWNIR_VERSION,
    Finding,
    OwnIRError,
    build_sarif,
    check_facts,
    load,
)

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

#: The pattern-level identity of a finding: everything a physical-anchor slice
#: promises NOT to touch. `column` is absent by construction, and `line` is here
#: because a slice that added a column while moving a line changed two things.
_PATTERN_FIELDS = ("file", "line", "code", "component", "event", "handler",
                   "message", "kind", "advisory", "severity", "ignore_reason")


def _pattern(f: Finding) -> tuple[Any, ...]:
    return tuple(getattr(f, k) for k in _PATTERN_FIELDS)


def _facts(subs: list[dict[str, Any]], version: int = OWNIR_VERSION) -> dict[str, Any]:
    return {"ownir_version": version, "module": "M",
            "components": [{"name": "C", "file": "C.cs", "subscriptions": subs}]}


def _strip_columns(subs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The same records as the PRE-SLICE producer would have emitted them."""
    return [{k: v for k, v in s.items() if k != "column"} for s in subs]


#: One fixture, exercising every shape the mini corpus is built around: a
#: subscription, two findings on ONE line (the case a column exists for), a
#: timer, an IDisposable field, a suppressed field, an advisory unresolved `+=`,
#: and a record with no line at all.
_FIXTURE: list[dict[str, Any]] = [
    {"event": "bus.Changed", "handler": "OnChanged", "line": 12, "column": 9,
     "source": "static", "source_type": "S"},
    {"event": "a.Ping", "handler": "OnA", "line": 42, "column": 9,
     "source": "static", "source_type": "S"},
    {"event": "b.Pong", "handler": "OnB", "line": 42, "column": 31,
     "source": "static", "source_type": "S"},
    {"event": "_timer.Tick", "handler": "OnTick", "line": 30, "column": 13,
     "resource": "timer"},
    {"event": "_stream", "handler": "", "line": 7, "column": 21,
     "resource": "disposable", "type": "MemoryStream"},
    {"event": "_ignored", "handler": "", "line": 8, "column": 21,
     "resource": "disposable", "type": "MemoryStream",
     "ignore_reason": "owned by the host, disposed there"},
    {"event": "ext.Ext", "handler": "OnExt", "line": 3, "column": 5,
     "resource": "unresolved-subscription"},
    # A record the producer could not place: no line, and therefore no column
    # either. It must stay locationless rather than acquiring half an anchor.
    {"event": "nowhere.Gone", "handler": "OnGone", "line": 0,
     "source": "static", "source_type": "S"},
]


def _regions(sarif: dict[str, Any]) -> list[dict[str, Any] | None]:
    return [r["locations"][0]["physicalLocation"].get("region")
            for r in sarif["runs"][0]["results"]]


def run() -> int:
    """Pin the column contract end to end; return 0/1."""
    fails: list[str] = []
    checks = 0

    def expect(cond: bool, msg: str) -> None:
        nonlocal checks
        checks += 1
        if not cond:
            fails.append(msg)

    # ---- 1. the OLD producer: no column, accepted, no startColumn ----------
    # Behaviour comes from the tolerant door; ACCEPTANCE by `load` is covered by the
    # explicit-null and valid-column controls in case 3, which go through a real
    # file. Here the point is only that an ABSENT column raises nothing anywhere.
    old_facts = _facts(_strip_columns(_FIXTURE))
    try:
        old = check_facts(old_facts)
    except OwnIRError as e:
        old = []
        fails.append(f"an old fact without `column` was rejected: {e}")
        checks += 1
    expect(all(f.column is None for f in old),
           f"every finding from a column-less producer must have column=None: "
           f"{[(f.event, f.column) for f in old]}")
    old_sarif = build_sarif(old)
    expect(all(r is None or "startColumn" not in r for r in _regions(old_sarif)),
           f"a column-less run must emit NO startColumn: {_regions(old_sarif)}")
    # ...and it must still emit the lines it always did, or the assertion above is
    # passing because the log is empty.
    expect(sum(1 for r in _regions(old_sarif) if r and "startLine" in r) == 7,
           f"the column-less run must still carry 7 startLines: "
           f"{_regions(old_sarif)}")

    # ---- 2. the NEW producer: the column reaches Finding and SARIF ---------
    new = check_facts(_facts(_FIXTURE))
    by_event = {f.event: f for f in new}
    for event, want in (("bus.Changed", 9), ("a.Ping", 9), ("b.Pong", 31),
                        ("_timer.Tick", 13), ("_stream", 21), ("_ignored", 21),
                        ("ext.Ext", 5)):
        got = by_event.get(event)
        expect(got is not None and got.column == want,
               f"{event}: expected column {want}, got "
               f"{None if got is None else got.column}")
    new_regions = [r for r in _regions(build_sarif(new)) if r is not None]
    expect(sorted((r["startLine"], r.get("startColumn")) for r in new_regions)
           == [(3, 5), (7, 21), (8, 21), (12, 9), (30, 13), (42, 9), (42, 31)],
           f"SARIF regions must carry every reported column: {new_regions}")

    # Column 1 is a REAL column, not a sentinel for "unknown". If anything in the
    # chain treated 1 as absent, this is where it shows.
    one = check_facts(_facts([{"event": "e", "handler": "h", "line": 5,
                               "column": 1, "source": "static",
                               "source_type": "S"}]))
    expect([f.column for f in one] == [1],
           f"column 1 must survive as a real column: {[f.column for f in one]}")
    expect(_regions(build_sarif(one)) == [{"startLine": 5, "startColumn": 1}],
           f"column 1 must reach SARIF: {_regions(build_sarif(one))}")

    # A column needs a line: SARIF's region grammar gives a bare column no meaning,
    # and half an anchor is not a cheaper anchor.
    lineless = by_event.get("nowhere.Gone")
    expect(lineless is not None and lineless.column is None,
           f"a record with no line must have no column: "
           f"{None if lineless is None else lineless.column}")
    orphan = check_facts(_facts([{"event": "e", "handler": "h", "line": 0,
                                  "column": 7, "source": "static",
                                  "source_type": "S"}]))
    expect([f.column for f in orphan] == [None],
           f"a column without a line must be dropped, got {[f.column for f in orphan]}")
    expect(_regions(build_sarif(orphan)) == [None],
           f"a file-level finding must carry no region at all: "
           f"{_regions(build_sarif(orphan))}")

    # ---- 3. an invalid column fails loud on the strict door ----------------
    def _load_raises(doc: dict[str, Any]) -> bool:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as fh:
            json.dump(doc, fh)
            path = fh.name
        try:
            load(path)
            return False
        except OwnIRError:
            return True
        finally:
            os.unlink(path)

    for bad in (0, -1, -7, True, False, "12", 3.5, [], {}):
        expect(_load_raises(_facts([{"event": "e", "handler": "h", "line": 1,
                                     "column": bad}])),
               f"column {bad!r} was accepted by load() — a column that was not "
               f"measured must be OMITTED, never coerced")
    # controls: a valid column and an EXPLICIT null both load. Explicit null is the
    # "producer says it does not know" spelling, and rejecting it would force
    # producers to choose between omitting a documented field and failing.
    for ok in (1, 4, 999):
        expect(not _load_raises(_facts([{"event": "e", "handler": "h", "line": 1,
                                         "column": ok}])),
               f"a valid column {ok} was wrongly rejected")
    expect(not _load_raises(_facts([{"event": "e", "handler": "h", "line": 1,
                                     "column": None}])),
           "an explicit null column was wrongly rejected (it is the documented "
           "'not measured' spelling)")

    # The TOLERANT door degrades instead of raising — the same policy `line` got in
    # #294 OD-3. `check_facts` is reachable directly (tests, embedders) on facts
    # that never went through `load`, and there a bad column must read as "no
    # column", never crash a finding path and never become a number.
    for bad in (0, -3, True, "12", 3.5, None, [], {}):
        try:
            got = check_facts(_facts([{"event": "e", "handler": "h", "line": 1,
                                       "column": bad, "source": "static",
                                       "source_type": "S"}]))
            expect([f.column for f in got] == [None],
                   f"tolerant door: column {bad!r} must degrade to None, got "
                   f"{[f.column for f in got]}")
        except (TypeError, ValueError) as e:
            fails.append(f"tolerant door: column {bad!r} crashed a finding path "
                         f"({type(e).__name__}: {e}) — it must degrade to None")
            checks += 1

    # ---- 4. old vs new producer: only the physical anchor moves ------------
    expect(len(old) == len(new),
           f"the two producers must report the same number of findings: "
           f"{len(old)} vs {len(new)}")
    expect([_pattern(f) for f in old] == [_pattern(f) for f in new],
           "the two producers must agree on every pattern-level field; only the "
           "physical anchor may move")
    expect([f.column for f in old] != [f.column for f in new],
           "the anchors MUST differ, or this fixture does not exercise the slice")
    # Compared as a multiset keyed by event rather than by emission order: the
    # findings are ordered by the core's own traversal, and pinning that order here
    # would make this case fail on an unrelated reordering while saying nothing
    # about the anchor.
    expect([f.column for f in old] == [None] * len(old),
           f"every old-producer anchor must be column-less: "
           f"{[f.column for f in old]}")
    expect({f.event: f.column for f in new} == {
               "bus.Changed": 9, "a.Ping": 9, "b.Pong": 31, "_timer.Tick": 13,
               "_stream": 21, "_ignored": 21, "ext.Ext": 5, "nowhere.Gone": None},
           f"the anchor move must be exactly absent -> the reported columns: "
           f"{ {f.event: f.column for f in new} }")

    # The same statement at the SARIF level: every result is identical except for
    # the added `startColumn`. Compared as whole documents with the columns removed,
    # so a change to a rule, a message, a level or a suppression cannot hide behind
    # the anchor diff.
    def _without_columns(doc: dict[str, Any]) -> Any:
        if isinstance(doc, dict):
            return {k: _without_columns(v) for k, v in doc.items()
                    if k != "startColumn"}
        if isinstance(doc, list):
            return [_without_columns(v) for v in doc]
        return doc

    expect(_without_columns(build_sarif(new)) == _without_columns(old_sarif),
           "with startColumn removed, the two producers' SARIF must be identical")
    # ...and the suppression really is in there, so the comparison above is not
    # passing over a log that lost it.
    sup = [r for r in build_sarif(new)["runs"][0]["results"] if "suppressions" in r]
    expect(len(sup) == 1 and sup[0]["suppressions"][0]["kind"] == "inSource",
           f"the fixture must carry exactly one in-source suppression: {sup}")

    # ---- 5. the renderer's caret heuristic is not on this path -------------
    # Behavioural half: a fact with no column produces no column, even though the
    # source line the caret renderer would look at has both a locatable identifier
    # AND indentation — the two things `_caret_col` falls back to. If the heuristic
    # were wired in anywhere, this is the assertion that breaks.
    caret = Diagnostic(code="OWN001", message="resource 'bus' leaks",
                       line=12, severity=Severity.ERROR)
    heuristic = caret._caret_col("        bus.Changed += OnChanged;")
    expect(heuristic is not None,
           "the caret heuristic must actually produce a column here, or this case "
           "proves nothing about it being unused")
    expect(by_event["bus.Changed"].column == 9,
           "sanity: the fixture's real column is 9")
    colless = check_facts(_facts([{"event": "bus.Changed", "handler": "OnChanged",
                                   "line": 12, "source": "static",
                                   "source_type": "S"}]))
    expect([f.column for f in colless] == [None],
           f"no column in the fact must mean no column in the finding, never the "
           f"caret's guess: {[f.column for f in colless]}")

    # Structural half: the modules on the fact -> Finding -> SARIF path must not
    # reference the heuristic at all. The behavioural check above only covers the
    # shapes it exercises; this one covers the ones nobody thought to write.
    for rel in ("ownlang/ownir.py", "ownlang/diag_sarif.py"):
        with open(os.path.join(_ROOT, rel), encoding="utf-8") as fh:
            body = fh.read()
        # A prose mention in a comment is exactly how this rule is documented, so
        # match a CALL/attribute use, not the name appearing in text.
        used = re.search(r"_caret_col\s*\(", body)
        expect(used is None,
               f"{rel} calls _caret_col — the renderer's caret heuristic must "
               f"never reach a physical anchor")

    # ---- 6. the published schema must state what the code enforces ---------
    # `spec/ownir.schema.json` is what a third-party producer reads to learn the
    # vocabulary. A schema that omitted `minimum: 1` would document a field the core
    # then rejects at load — the producer would ship a conforming 0 and get an error
    # it had no way to anticipate.
    with open(os.path.join(_ROOT, "spec", "ownir.schema.json"), encoding="utf-8") as fh:
        schema = json.load(fh)
    col_schema = schema["$defs"]["resourceRecord"]["properties"].get("column")
    expect(col_schema is not None,
           "spec/ownir.schema.json does not declare the `column` field")
    if col_schema is not None:
        expect(col_schema.get("minimum") == 1,
               f"the schema must publish `minimum: 1` for column, got "
               f"{col_schema.get('minimum')!r} — the core rejects 0 and below")
        expect(sorted(col_schema.get("type", [])) == ["integer", "null"],
               f"column must be declared nullable (the documented 'not measured' "
               f"spelling), got {col_schema.get('type')!r}")

    for f in fails:
        print(f"OWNIR-COLUMN FAIL: {f}")
    print(f"ownir column: {checks - len(fails)}/{checks} physical-anchor "
          f"contract checks pass")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
