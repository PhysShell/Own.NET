#!/usr/bin/env python3
"""Fact-level differential parity for the obligation-protocol analysis
(OBL001-005, P-025) — P-022 #259 checkpoint 4b.

The third OwnIR-fact sidecar analysis, beside `tests/test_di_eff_fact_parity.py`
(DI001-005 and EFF001) and built the same way: there is no `.own` surface, so
Python remains the reference. This generator states protocol **rules** and
per-method **event trees** as the raw documents a frontend emits, runs the
*real* `ownlang.obligations.check_protocols` / `unmatched_scopes` over them, and
freezes each violation WHOLE — `protocol`, `method`, `file`, `line`, `kind`,
`definite`, `open_line`, `barrier_desc`, `close_line` — plus the dead-rule list,
into `tests/fixtures/obligation_fact_parity.json`.
`rust/crates/own-analysis/tests/obligation_parity.rs` replays the same
documents through the ported analysis and must reproduce the exact ordered
list, with **zero Python**.

Two things this family deliberately does NOT do:

* it does not freeze codes, messages or evidence slices. Those are the bridge's
  (`spec/Bridge.md` BR-P3), they are Layer 3, and the verdict fixture family
  already owns that surface. A violation is the *facts* a finding is
  synthesized from; keeping the two apart is what makes a divergence say
  whether the walk or the phrasing drifted.
* it does not hand the two sides pre-parsed values. Cases carry the raw
  `protocols[]` / `protocol_functions[]` records, so each side builds them with
  its own half of the shared grammar — Python's `parse_protocol` / `parse_method`
  and Rust's `own_ir::protocol`. A grammar that accepted the same documents and
  built different values would otherwise be invisible here.

The cases are seeded from `tests/test_obligations.py` §1 (the core walk), which
is the behaviour map this port has to reproduce, and extended with the shapes
that suite asserts through other layers or not at all: the sort key across
files, a protocol over several methods, an open with no line, and nested
control flow.

Run:  python tests/test_obligation_fact_parity.py            (verify)
      python tests/test_obligation_fact_parity.py --write    (regenerate)
      python tests/run_tests.py                              (runs it in the suite)
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.obligations import (
    MethodEvents,
    Protocol,
    Violation,
    check_protocols,
    parse_method,
    parse_protocol,
    unmatched_scopes,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                       "obligation_fact_parity.json")

# --- the rule side, as documents ---------------------------------------------

#: The canonical protocol of `tests/test_obligations.py`: `IsLoaded = false`
#: opens, `IsLoaded = true` closes, `OnPropertyChanged(Document|Rows)` is a
#: barrier, `OnPropertyChanged(IsBusy|IsLoaded)` is allowed.
DOC_LOAD: dict[str, Any] = {
    "name": "DocLoad",
    "opens": {"kind": "assign", "target": "IsLoaded", "value": False},
    "closes": {"kind": "assign", "target": "IsLoaded", "value": True},
    "barriers": [{"kind": "call", "callee": "OnPropertyChanged",
                  "args": ["Document", "Rows"]}],
    "allow": [{"kind": "call", "callee": "OnPropertyChanged",
               "args": ["IsBusy", "IsLoaded"]}],
}

#: A call-driven protocol: `BeginUpdate()` opens, `EndUpdate()` closes, and the
#: barrier is a bare call with no argument narrowing.
BATCH_UPDATE: dict[str, Any] = {
    "name": "BatchUpdate",
    "opens": {"kind": "call", "callee": "BeginUpdate"},
    "closes": {"kind": "call", "callee": "EndUpdate"},
    "barriers": [{"kind": "call", "callee": "Refresh"}],
}


#: A protocol whose barrier is an *assign* matcher rather than a call — the
#: `target = ...` description branch, which no call barrier can reach.
DIRTY_FLAG: dict[str, Any] = dict(
    DOC_LOAD, name="DirtyFlag",
    barriers=[{"kind": "assign", "target": "Dirty"}], allow=[])

#: The same, narrowed to one written value: a write of the other value is not a
#: crossing.
DIRTY_TRUE: dict[str, Any] = dict(
    DOC_LOAD, name="DirtyTrue",
    barriers=[{"kind": "assign", "target": "Dirty", "value": True}], allow=[])


def _proto(**kw: Any) -> dict[str, Any]:
    out = dict(DOC_LOAD)
    out.update(kw)
    return out


# --- the fact side, as documents ---------------------------------------------

def _open(line: int = 10) -> dict[str, Any]:
    return {"ev": "assign", "target": "IsLoaded", "value": False, "line": line}


def _close(line: int = 90) -> dict[str, Any]:
    return {"ev": "assign", "target": "IsLoaded", "value": True, "line": line}


def _opaque(target: str = "IsLoaded", line: int = 20) -> dict[str, Any]:
    return {"ev": "assign", "target": target, "line": line}


def _notify(arg: str | None = "Document", line: int = 50) -> dict[str, Any]:
    ev: dict[str, Any] = {"ev": "call", "callee": "OnPropertyChanged", "line": line}
    if arg is not None:
        ev["arg"] = arg
    return ev


def _call(callee: str, line: int) -> dict[str, Any]:
    return {"ev": "call", "callee": callee, "line": line}


def _if(line: int, then: list[dict[str, Any]],
        orelse: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"ev": "if", "line": line, "then": then, "else": orelse or []}


def _while(line: int, body: list[dict[str, Any]]) -> dict[str, Any]:
    return {"ev": "while", "line": line, "body": body}


def _method(*events: dict[str, Any], name: str = "Ns.VM.Load",
            file: str = "VM.cs") -> dict[str, Any]:
    return {"name": name, "file": file, "events": list(events)}


# --- the cases ---------------------------------------------------------------
#
# Each entry is (name, protocol documents, method documents). The comment on a
# case names the behaviour it is the control for; the checkpoint note
# (docs/notes/p022-bridge-verdict-checkpoint4b.md) carries the full ledger.

_CASES: list[tuple[str, list[dict[str, Any]], list[dict[str, Any]]]] = [
    # -- the straight line, and its fixed twin ---------------------------------
    ("straight_line_barrier_crossing",
     [DOC_LOAD], [_method(_open(), _notify(), _close())]),
    ("close_before_the_barrier_is_clean",
     [DOC_LOAD], [_method(_open(), _close(), _notify())]),
    ("nothing_open_is_clean",
     [DOC_LOAD], [_method(_notify(), _close())]),

    # -- matching ---------------------------------------------------------------
    ("allow_beats_barrier",
     [DOC_LOAD], [_method(_open(), _notify("IsBusy", 20), _close())]),
    ("args_narrowing_rejects_another_argument",
     [DOC_LOAD], [_method(_open(), _notify("Totals", 20), _close())]),
    ("args_narrowing_rejects_an_unknown_argument",
     [DOC_LOAD], [_method(_open(), _notify(None, 21), _close())]),
    ("an_unnamed_call_is_neutral",
     [DOC_LOAD], [_method(_open(), _call("RebuildIndexes", 20), _notify(), _close())]),
    ("a_bare_call_barrier_matches_any_argument",
     [BATCH_UPDATE], [_method(_call("BeginUpdate", 10), _call("Refresh", 20),
                              _call("EndUpdate", 30))]),
    ("a_second_barrier_matcher_can_fire",
     [DOC_LOAD], [_method(_open(), _notify("Rows", 50), _close())]),
    ("an_assign_barrier_describes_itself_as_a_write",
     [DIRTY_FLAG], [_method(_open(), _opaque("Dirty"), _close())]),
    ("a_value_narrowed_assign_barrier_ignores_the_other_write",
     [DIRTY_TRUE], [_method(_open(), {"ev": "assign", "target": "Dirty",
                                      "value": False, "line": 20},
                            {"ev": "assign", "target": "Dirty",
                             "value": True, "line": 21}, _close())]),

    # -- the definite/maybe split ----------------------------------------------
    ("a_barrier_in_a_branch_stays_definite",
     [DOC_LOAD], [_method(_open(), _if(20, [_notify()]), _close())]),
    ("half_closed_at_a_merge_is_a_maybe",
     [DOC_LOAD], [_method(_open(), _if(20, [_close(21)]), _notify(line=30),
                          _close(40))]),
    ("open_on_some_path_is_a_maybe",
     [DOC_LOAD], [_method(_if(20, [_open()]), _notify(line=30))]),
    ("reopening_keeps_the_earliest_open_site",
     [DOC_LOAD], [_method(_open(20), _open(10), _notify(), _close())]),
    ("a_later_reopen_does_not_move_the_provenance",
     [DOC_LOAD], [_method(_open(10), _open(20), _notify(), _close())]),
    ("both_arms_open_keeps_it_definite_and_joins_the_earliest_open",
     [DOC_LOAD], [_method(_if(20, [_open(21)], [_open(11)]), _notify(line=30),
                          _close())]),

    # -- exits -------------------------------------------------------------------
    ("an_open_falling_off_the_end_anchors_at_the_open",
     [DOC_LOAD], [_method(_open())]),
    ("an_early_return_while_open_reports_at_the_return",
     [DOC_LOAD], [_method(_open(), _if(20, [{"ev": "return", "line": 25}]),
                          _close())]),
    ("a_throw_while_open_reports_at_the_throw",
     [DOC_LOAD], [_method(_open(), {"ev": "throw", "line": 30})]),
    ("an_exit_leak_carries_no_late_close_hop",
     [DOC_LOAD], [_method(_open(), _if(20, [{"ev": "throw", "line": 25}]), _close())]),
    ("code_after_a_partially_returning_branch_still_runs",
     [DOC_LOAD], [_method(_open(), _if(20, [{"ev": "return", "line": 25}]),
                          _notify(), _close())]),
    ("only_the_returning_path_leaks",
     [DOC_LOAD], [_method(_open(), _if(20, [{"ev": "return", "line": 25}], [_close()]))]),
    ("both_arms_leaving_ends_the_method",
     [DOC_LOAD], [_method(_open(), _if(20, [{"ev": "return", "line": 25}],
                                       [{"ev": "throw", "line": 26}]), _notify())]),
    ("exit_barriers_false_silences_the_exit_only",
     [_proto(exit_barriers=False)], [_method(_open(), _notify(), _close())]),
    ("exit_barriers_false_with_no_barrier_is_clean",
     [_proto(exit_barriers=False)], [_method(_open())]),
    ("events_after_a_top_level_return_are_unreachable",
     [DOC_LOAD], [_method(_open(), {"ev": "return", "line": 20}, _open(30),
                          _notify())]),
    ("an_open_with_no_line_anchors_at_zero",
     [DOC_LOAD], [_method({"ev": "assign", "target": "IsLoaded", "value": False})]),

    # -- loops ---------------------------------------------------------------------
    ("a_loop_may_run_zero_times_so_a_close_inside_is_a_maybe",
     [DOC_LOAD], [_method(_open(), _while(20, [_close(21)]), _notify(line=30),
                          _close(40))]),
    ("a_barrier_in_a_loop_reports_exactly_once",
     [DOC_LOAD], [_method(_open(), _while(20, [_notify()]), _close())]),
    ("a_barrier_in_a_nested_loop_reports_exactly_once",
     [DOC_LOAD], [_method(_open(), _while(20, [_while(21, [_notify()])]), _close())]),
    ("open_close_cycling_in_a_loop_converges_and_stays_definite",
     [DOC_LOAD], [_method(_open(), _while(20, [_close(21), _open(22)]),
                          _notify(line=30), _close(40))]),
    ("a_loop_body_that_always_leaves_still_converges",
     [DOC_LOAD], [_method(_open(), _while(20, [{"ev": "return", "line": 21}]),
                          _notify(line=30), _close(40))]),
    ("an_if_inside_a_loop_reports_once",
     [DOC_LOAD], [_method(_open(), _while(20, [_if(21, [_notify()])]), _close())]),
    ("a_loop_inside_an_if_reports_once",
     [DOC_LOAD], [_method(_open(), _if(20, [_while(21, [_notify()])]), _close())]),

    # -- the opaque-write asymmetry ---------------------------------------------
    ("an_opaque_write_may_discharge_downgrading_to_a_maybe",
     [DOC_LOAD], [_method(_open(), _opaque(), _notify(), _close())]),
    ("an_opaque_write_never_opens_an_obligation",
     [DOC_LOAD], [_method(_opaque(line=5), _notify())]),
    ("an_opaque_write_to_an_untracked_member_is_inert",
     [DOC_LOAD], [_method(_open(), _opaque("Title"), _notify(), _close())]),
    ("an_opaque_write_leaks_off_the_end_as_a_maybe",
     [DOC_LOAD], [_method(_open(), _opaque())]),

    # -- scope ---------------------------------------------------------------------
    ("a_type_method_suffix_matches",
     [_proto(scope={"methods": ["VM.Load"]})],
     [_method(_open(), _notify(), _close())]),
    ("an_exact_name_matches",
     [_proto(scope={"methods": ["Ns.VM.Load"]})],
     [_method(_open(), _notify(), _close())]),
    ("a_prefix_is_not_a_suffix_and_a_sibling_is_out_of_scope",
     [_proto(scope={"methods": ["VM.Load"]})],
     [_method(_open(), _notify(), _close(), name="Ns.VM.LoadAll"),
      _method(_open(), _notify(), _close(), name="Ns.OtherVM.Load2")]),
    ("a_scope_matching_nothing_is_a_dead_rule",
     [_proto(scope={"methods": ["VM.Misspelled"]})],
     [_method(_open(), name="Ns.OtherVM.Reload")]),
    ("an_unscoped_protocol_is_never_a_dead_rule",
     [DOC_LOAD], []),
    ("a_dead_rule_and_a_live_one_together",
     [_proto(scope={"methods": ["VM.Misspelled"]}),
      dict(BATCH_UPDATE, scope={"methods": ["VM.Load"]})],
     [_method(_call("BeginUpdate", 10), _call("Refresh", 20))]),

    # -- several protocols, several methods --------------------------------------
    ("two_protocols_do_not_interfere",
     [DOC_LOAD, BATCH_UPDATE],
     [_method(_open(), _call("BeginUpdate", 20), _call("EndUpdate", 30),
              _notify(), _close())]),
    ("two_protocols_both_fire_on_one_method",
     [DOC_LOAD, BATCH_UPDATE],
     [_method(_open(), _call("BeginUpdate", 20), _notify(), _call("Refresh", 51),
              _close(), _call("EndUpdate", 91))]),
    ("one_protocol_over_several_methods",
     [DOC_LOAD],
     [_method(_open(), _notify(), _close(), name="Ns.VM.LoadA"),
      _method(_open(), _notify(), _close(), name="Ns.VM.LoadB")]),

    # -- ordering ------------------------------------------------------------------
    ("two_barriers_sort_by_line",
     [DOC_LOAD], [_method(_open(), _notify(line=60), _notify("Rows", 50), _close())]),
    ("equal_lines_sort_by_barrier_description",
     [DOC_LOAD], [_method(_open(), _notify("Rows", 50), _notify("Document", 50),
                          _close())]),
    ("violations_sort_by_file_before_line",
     [DOC_LOAD],
     [_method(_open(), _notify(line=60), _close(), name="Ns.Z.Load", file="z.cs"),
      _method(_open(), _notify(line=70), _close(), name="Ns.B.Load", file="b.cs")]),
    ("equal_locations_sort_by_protocol_then_barrier",
     [DOC_LOAD, BATCH_UPDATE],
     [_method(_open(), _call("BeginUpdate", 11), _notify(line=50),
              _call("Refresh", 50), _close(), _call("EndUpdate", 91))]),

    # -- the late-close hop ----------------------------------------------------------
    ("the_late_close_is_the_earliest_one_after_the_barrier",
     [DOC_LOAD], [_method(_open(), _notify(), _close(70), _close(80))]),
    ("a_close_on_the_barrier_line_is_not_late",
     [DOC_LOAD], [_method(_open(), _notify(), _close(50))]),
    ("a_close_before_the_barrier_is_not_a_late_close",
     [DOC_LOAD], [_method(_open(), _close(20), _open(30), _notify(), _close(90))]),
    ("an_unreachable_close_still_counts_as_evidence",
     [DOC_LOAD],
     [_method(_open(), _notify(), {"ev": "return", "line": 60}, _close(70))]),
    ("a_close_only_inside_a_loop_body_still_counts_as_evidence",
     [DOC_LOAD], [_method(_open(), _notify(), _while(60, [_close(70)]))]),
]


# --- running the reference ------------------------------------------------------

def _violation_row(v: Violation) -> dict[str, Any]:
    """One violation, whole. Member order is the reference dataclass's, so a
    reader can diff a row against `obligations.Violation` by eye."""
    return {
        "protocol": v.protocol,
        "method": v.method,
        "file": v.file,
        "line": v.line,
        "kind": v.kind,
        "definite": v.definite,
        "open_line": v.open_line,
        "barrier_desc": v.barrier_desc,
        "close_line": v.close_line,
    }


def _run(protocols: list[dict[str, Any]],
         methods: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    parsed_protocols: list[Protocol] = [parse_protocol(p) for p in protocols]
    parsed_methods: list[MethodEvents] = [parse_method(m) for m in methods]
    violations = [_violation_row(v)
                  for v in check_protocols(parsed_protocols, parsed_methods)]
    dead = [p.name for p in unmatched_scopes(parsed_protocols, parsed_methods)]
    return violations, dead


def build() -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for name, protocols, methods in _CASES:
        violations, dead = _run(protocols, methods)
        cases.append({
            "name": name,
            "protocols": protocols,
            "methods": methods,
            "expected": violations,
            "dead": dead,
        })
    return {
        "comment": (
            "GENERATED by tests/test_obligation_fact_parity.py --write; do not edit. "
            "Python (ownlang.obligations) is authoritative; "
            "rust/crates/own-analysis/tests/obligation_parity.rs replays the same raw "
            "protocol/event documents through the ported analysis and must reproduce "
            "every violation member and the dead-rule list exactly (#259 cp4b). "
            "Codes, messages and evidence slices are NOT here: those are the bridge's "
            "(BR-P3) and the Layer 3 verdict family owns them."
        ),
        "obligation_parity_version": 1,
        "cases": cases,
    }


def _render(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _duplicate_case_names() -> list[str]:
    seen: set[str] = set()
    dupes: list[str] = []
    for name, _, _ in _CASES:
        if name in seen:
            dupes.append(name)
        seen.add(name)
    return dupes


def run() -> int:
    dupes = _duplicate_case_names()
    if dupes:
        print(f"FAIL[obligation-parity]: duplicate case name(s) {dupes} — a case "
              f"name is how a divergence is reported, so it must be unique")
        return 1
    expected = _render(build())
    if not os.path.exists(FIXTURE):
        print(f"FAIL[obligation-parity]: {FIXTURE} missing; regenerate with "
              f"'python tests/test_obligation_fact_parity.py --write'")
        return 1
    with open(FIXTURE, encoding="utf-8") as f:
        actual = f.read()
    if actual != expected:
        print(f"FAIL[obligation-parity]: {FIXTURE} is stale (the walk, the sort key "
              f"or a case changed); regenerate with "
              f"'python tests/test_obligation_fact_parity.py --write' and re-run the "
              f"Rust side (cd rust && cargo test -p own-analysis)")
        return 1
    data = json.loads(actual)
    n_violations = sum(len(c["expected"]) for c in data["cases"])
    n_dead = sum(len(c["dead"]) for c in data["cases"])
    silent = sum(1 for c in data["cases"] if not c["expected"])
    print(f"obligation fact parity OK: {len(data['cases'])} cases "
          f"({n_violations} violations, {n_dead} dead rules, {silent} silence "
          f"controls) verified in sync")
    return 0


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
        with open(FIXTURE, "w", encoding="utf-8") as f:
            f.write(_render(build()))
        print(f"wrote {FIXTURE}")
        raise SystemExit(0)
    raise SystemExit(run())
