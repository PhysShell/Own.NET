#!/usr/bin/env python3
"""
RED contract for #317 — real Roslyn source columns from OwnIR fact to SARIF.

Today a finding's position collapses to a line: `LineOf(node)` in the extractor
throws `.Character` away, the fact carries `line`, `Finding` carries `line`, and
SARIF emits `startLine`. OwnAudit's `finding-occurrence/v1` anchors on
`path + startLine + startColumn`, so every own-check finding currently anchors
line-only.

This file is the executable specification of the fix, written BEFORE it. It was
deliberately NOT all-red: on `main@0ded835` 18 of its 28 checks failed and 10
passed. Those 10 are the point as much as the 18 - they pin what must NOT move
(the flow-local anchor line, OWNIR_VERSION, and the human/GitHub/MSBuild
renderings byte for byte), so a "fix" that moved any of them would be caught by a
check that was already green. A contract made all-red on purpose proves less.

THE CASE THAT DECIDES THE SLICE
-------------------------------
`check_facts` has two flow-local shapes and they are NOT the same:

  * the special `OWN025` branch (POOL005) reports at the *view* site — `d.line`,
    the core diagnostic's line, deliberately not the acquire;
  * every other flow-local verdict, OWN001 among them, reports at the *acquire*
    site — `sub["line"]`, which `_lower_flow` carried over from the Roslyn
    `acquire` op (`ownir.py:2234` -> `acq_line`).

The dedupe comment at `ownir.py:2911` states it outright: a local that leaks on
several exits yields one core diagnostic per exit, and "for a flow-local every
such diagnostic remaps to the same acquire line (`sub["line"]`)". Verified by
running `flow_leak_two_exits.facts.json`: the acquire is at 105, the exits at
106, and the finding lands on **105**.

So flow-local OWN001 is producer-solvable: its coordinate comes from a Roslyn
fact, not from a `.own` parse. `test_flow_local_acquire_anchor` is the check that
proves the column travelled the whole way — through the flow op AND the handle —
rather than only through the direct subscription facts.

Run:  PYTHONUTF8=1 python3 tests/test_ownir_column.py
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.ownir import (
    OWNIR_VERSION,
    OwnIRError,
    build_sarif,
    check_facts,
    load,
    render_finding,
    to_module,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ownir")

#: The column the extractor would report for the anchored node. Deliberately not
#: 1: a fabricated "first column" is indistinguishable from a real one, which is
#: exactly the failure the OwnAudit anchor contract forbids.
COL = 21

fails: list[str] = []
checks = 0


def check(cond: bool, msg: str) -> None:
    global checks
    checks += 1
    if not cond:
        fails.append(msg)


def _write(obj: dict) -> str:
    fd, path = tempfile.mkstemp(suffix=".facts.json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    return path


def _raises(obj: dict) -> bool:
    # `finally`, not a plain unlink after `load`: this helper exists to run inputs that
    # RAISE, so the cleanup has to be on the path that raises - which is every call.
    path = _write(obj)
    try:
        load(path)
    except OwnIRError:
        return True
    except Exception:
        return False
    else:
        return False
    finally:
        os.remove(path)


def _subscription_facts(column: int | None = None) -> dict:
    sub: dict = {"event": "bus.CustomerChanged", "handler": "OnCustomerChanged",
                 "line": 12, "released": False}
    if column is not None:
        sub["column"] = column
    return {"ownir_version": 0, "module": "WpfApp",
            "components": [{"name": "CustomerViewModel", "file": "CustomerViewModel.cs",
                            "subscriptions": [sub]}]}


def _flow_acquire_facts(column: int | None = None) -> dict:
    """The two-exits shape: the acquire is at 105, the leaking exits at 106.

    The core emits one diagnostic per exit (line 106); the finding must remap to
    the acquire. If the column ever came from the diagnostic instead of the fact,
    this fixture reports 106 and the mismatch is unmissable.
    """
    acquire: dict = {"op": "acquire", "var": "tfLeak", "line": 105}
    if column is not None:
        acquire["column"] = column
    return {"ownir_version": 0, "module": "Extracted", "components": [],
            "functions": [{"name": "FlowLocalsSample.TryNeverDisposed",
                           "file": "FlowLocalsSample.cs",
                           "body": [acquire,
                                    {"op": "if", "line": 106,
                                     "then": [{"op": "return", "var": None, "line": 106}],
                                     "else": []},
                                    {"op": "use", "var": "tfLeak", "line": 106}]}]}


def _region(finding_index: int, findings: list) -> dict:
    doc = build_sarif(findings)
    results = doc["runs"][0]["results"]
    phys = results[finding_index]["locations"][0]["physicalLocation"]
    return phys.get("region") or {}


def run() -> int:
    # ---- 1. BACKWARD COMPATIBILITY -----------------------------------------
    # A fact with no column is the entire recorded corpus and every older
    # extractor build. It must keep loading, and its SARIF must stay EXACTLY as
    # it is - an absent column is absent, never a substituted 1.
    old = check_facts(_subscription_facts())
    check(len(old) == 1, f"baseline: expected 1 finding, got {len(old)}")
    if old:
        check(getattr(old[0], "column", "MISSING") is None,
              "a fact without a column must yield Finding.column None "
              f"(got {getattr(old[0], 'column', 'MISSING')!r})")
        reg = _region(0, old)
        check("startLine" in reg and "startColumn" not in reg,
              f"a column-less finding must emit startLine only, got {reg}")

    # ---- 2. THE COLUMN TRAVELS: subscription fact ---------------------------
    new = check_facts(_subscription_facts(COL))
    check(len(new) == 1, f"columned: expected 1 finding, got {len(new)}")
    if new:
        check(getattr(new[0], "column", None) == COL,
              f"Finding.column must be {COL}, got {getattr(new[0], 'column', 'MISSING')!r}")
        check(new[0].line == 12, f"the line must not move: {new[0].line}")
        reg = _region(0, new)
        check(reg.get("startLine") == 12 and reg.get("startColumn") == COL,
              f"SARIF region must carry both coordinates, got {reg}")

    # ---- 3. THE DECIDING CASE: flow-local acquire anchor --------------------
    # The acquire is at 105:COL, the diagnostics at 106. Both coordinates must
    # come from the ACQUIRE FACT, not from the core diagnostic. A column that
    # arrived via `d` would show up here as 106 or as None.
    flow = check_facts(_flow_acquire_facts(COL))
    check(len(flow) == 1, f"flow-local: expected 1 finding, got {len(flow)}")
    if flow:
        f0 = flow[0]
        check((f0.file, f0.line) == ("FlowLocalsSample.cs", 105),
              f"flow-local must anchor on the acquire line, got {f0.file}:{f0.line}")
        check(getattr(f0, "column", None) == COL,
              "flow-local must anchor on the acquire COLUMN too - the column has to "
              "travel through the flow op and the flow-local handle, not only through "
              f"direct subscription facts (got {getattr(f0, 'column', 'MISSING')!r})")
        reg = _region(0, flow)
        check(reg.get("startLine") == 105 and reg.get("startColumn") == COL,
              f"flow-local SARIF must carry the acquire pair, got {reg}")
    # and with no column on the acquire, nothing is invented
    flow_old = check_facts(_flow_acquire_facts())
    if flow_old:
        check(getattr(flow_old[0], "column", "MISSING") is None,
              "a column-less acquire must stay column-less - never the diagnostic's, "
              "never 1")

    # ---- 4. VALIDATION: a column is a real 1-based coordinate or nothing ----
    for bad in (0, -1, True, False, "21", 21.0, None if False else [21]):
        facts = _subscription_facts()
        facts["components"][0]["subscriptions"][0]["column"] = bad
        check(_raises(facts),
              f"column={bad!r} ({type(bad).__name__}) must raise OwnIRError")
    # the flow op is validated too - the same field, the same rule
    bad_flow = _flow_acquire_facts()
    bad_flow["functions"][0]["body"][0]["column"] = 0
    check(_raises(bad_flow), "an acquire op with column=0 must raise OwnIRError")

    # ---- 5. THE COLUMN MUST DISCRIMINATE -----------------------------------
    # Two findings identical in every emitted field except the column. The dedupe
    # key already includes `line` (ownir.py:2913 says so); without `column` in it
    # these collapse to one, and the "several findings on one line" fixture
    # becomes decorative - a new key that changes no outcome.
    two = _subscription_facts(COL)
    second = copy.deepcopy(two["components"][0]["subscriptions"][0])
    second["column"] = COL + 30
    two["components"][0]["subscriptions"].append(second)
    got = check_facts(two)
    check(len(got) == 2,
          "two findings on one line differing only by column must stay TWO - the "
          f"dedupe key is missing `column` (got {len(got)})")
    if len(got) == 2:
        check({getattr(x, "column", None) for x in got} == {COL, COL + 30},
              f"both columns must survive, got {[getattr(x, 'column', None) for x in got]}")
        check([getattr(x, "column", None) for x in got] == sorted(
                  getattr(x, "column", 0) for x in got),
              "the deterministic sort key must order by column within a line")

    # ---- 5b. EVERY HANDLE-MINTING PATH, NOT JUST THE OBVIOUS ONE -----------
    #      A flow-local handle is minted in five places. A column that travels only
    #      the direct `acquire` would leave whole categories line-only, so each path
    #      is exercised here rather than assumed from the code reading.
    def _fn(body):
        return {"ownir_version": 0, "module": "M", "components": [],
                "functions": [{"name": "F.G", "file": "F.cs", "body": body}]}

    # a contract param that became an owned obligation (`_lower_fn_params`)
    prm = check_facts({"ownir_version": 0, "module": "M", "components": [],
                       "functions": [{"name": "F.G", "file": "F.cs",
                                      "params": [{"name": "owned", "line": 30,
                                                  "column": 26, "effect": "consume"}],
                                      "body": [{"op": "use", "var": "owned", "line": 31}]}]})
    check([(f.line, f.column) for f in prm] == [(30, 26)],
           f"param path lost the column: {[(f.line, f.column) for f in prm]}")

    # a fresh-returning call result
    res = check_facts(_fn([
        {"op": "call", "callee": "System.IO.File.Create", "sig": "Create(string)",
         "result": "d", "args": [], "line": 20, "column": 11},
        {"op": "use", "var": "d", "line": 21}]))
    check([(f.line, f.column) for f in res] == [(20, 11)],
           f"call-result path lost the column: {[(f.line, f.column) for f in res]}")

    # a branch acquire referenced after the merge (the HOISTED path -
    # `_hoisted_branch_locals`, the one most easily forgotten)
    hoi = check_facts(_fn([
        {"op": "if", "line": 43,
         "then": [{"op": "acquire", "var": "h", "line": 44, "column": 21}], "else": []},
        {"op": "use", "var": "h", "line": 46}]))
    check([(f.line, f.column) for f in hoi] == [(44, 21)],
           f"hoisted-branch path lost the column: {[(f.line, f.column) for f in hoi]}")

    # `alias_join` is the fifth path. Its handle carries the column, but a finding
    # NEVER anchors on the alias site: the alias shares the source's obligation, so
    # every probed shape reports at the original acquire. Recorded as observed
    # behaviour rather than claimed as coverage - if that ever changes, this check
    # fails and someone decides deliberately which site should anchor.
    alias_facts = _fn([
        {"op": "acquire", "var": "x", "line": 12, "column": 7},
        {"op": "alias_join", "var": "c", "src": "x", "line": 13, "column": 9},
        {"op": "use", "var": "c", "line": 14}])

    # (a) the HANDLE keeps the alias site's OWN coordinate. Observed directly via
    #     `to_module`, because the finding in (b) cannot see it: delete the column
    #     from the alias handle and (b) stays green, which would leave this path
    #     covered in appearance only.
    _, handles = to_module(alias_facts)
    alias_handle = next(
        (h for h in handles.values()
         if h.get("resource") == "flow-local" and h.get("event") == "c"), None)
    check(alias_handle is not None, "the alias_join handle was never minted")
    if alias_handle is not None:
        check((alias_handle.get("line"), alias_handle.get("column")) == (13, 9),
              f"alias_join handle lost its own coordinate: {alias_handle}")

    # (b) and the FINDING still anchors at the SOURCE acquire, because the alias
    #     shares that obligation rather than creating a second one. A separate
    #     claim from (a), so a separate check: if the diagnostic semantics ever
    #     change, this fails and someone decides deliberately which site anchors.
    ali = check_facts(alias_facts)
    check([(f.line, f.column, f.event) for f in ali] == [(12, 7, "x")],
           f"alias_join must still anchor at the source acquire: "
           f"{[(f.line, f.column, f.event) for f in ali]}")

    # ---- 6. THE MESSAGE IS NOT A COORDINATE SOURCE -------------------------
    # `Diagnostic._caret_col` recovers a caret column by searching the source line
    # for a name pulled out of the message text. That heuristic must never reach
    # SARIF: a message full of misleading numbers changes nothing.
    misleading = _subscription_facts(COL)
    s = misleading["components"][0]["subscriptions"][0]
    s["event"] = "bus.Changed99"
    s["handler"] = "OnChanged(1, 2, 3)"
    mis = check_facts(misleading)
    if mis:
        check(getattr(mis[0], "column", None) == COL,
              "the emitted column must come from the fact, not from digits in the message")

    # ---- 7. THE COLUMN FOLLOWS THE LOCATION, NOT THE TEXT -------------------
    # Same source, different indentation: the extractor reports a different
    # column for the same construct, and the pipeline carries whatever it says.
    indented = check_facts(_subscription_facts(COL + 4))
    if indented and new:
        check(getattr(indented[0], "column", None) == COL + 4
              and getattr(new[0], "column", None) == COL,
              "a re-indented construct must carry ITS column, not a remembered one")

    # ---- 8. THINGS THAT MUST NOT MOVE --------------------------------------
    check(OWNIR_VERSION == 0,
          f"OWNIR_VERSION must stay 0 - an optional field with a safe default is "
          f"additive (spec/OwnIR.md §2), got {OWNIR_VERSION}")
    if old and new:
        for fmt in ("human", "github", "msbuild"):
            check(render_finding(old[0], fmt) == render_finding(new[0], fmt),
                  f"{fmt} rendering must be byte-for-byte unchanged by the column - "
                  "column-aware rendering is a separate decision, not a side effect")

    # ---- 9. THE FIELD IS DECLARED LAST -------------------------------------
    # Positional construction is used across this module; a field inserted in the
    # middle would silently re-bind every positional argument after it.
    from dataclasses import fields as dc_fields

    from ownlang.ownir import Finding
    names = [f.name for f in dc_fields(Finding)]
    check(names[-1] == "column",
          f"`column` must be the LAST field of Finding, after ignore_reason; order is {names}")

    for f in fails:
        print(f"FAIL: {f}")
    print(f"ownir column contract: {len(fails)} failed of {checks} checks")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
