#!/usr/bin/env python3
"""Obligation-protocol tests — OBL001-005 (P-025).

Three layers, all zero-dependency:
  1. the pure core analysis (ownlang/obligations.py): the path-sensitive walk,
     the {OPEN, CLOSED} set lattice (definite/maybe split), loop fixpoints with
     single emission, exit barriers, allow lists, the opaque-write discharge
     asymmetry, and scoping;
  2. the OwnIR bridge (ownlang/ownir.py): the optional `protocols` /
     `protocol_functions` blocks route through check_facts to OBL Findings at
     their C# locations, with the opened -> barrier (-> closed-late) evidence
     slice, line-free messages, and fail-loud load() validation;
  3. the schema pin (spec/ownir.schema.json): the event and matcher
     vocabularies are bound to the code's authoritative sets BOTH ways, the
     flow-op discipline applied to the new blocks.

Run:  python tests/test_obligations.py
      python tests/run_tests.py     (runs it as part of the suite)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.obligations import (
    EVENT_KINDS,
    MATCHER_KINDS,
    AssignEv,
    CallEv,
    IfEv,
    Matcher,
    MethodEvents,
    Protocol,
    ProtocolFactsError,
    ReturnEv,
    ThrowEv,
    WhileEv,
    check_protocols,
    parse_events,
    parse_method,
    parse_protocol,
    unmatched_scopes,
)
from ownlang.ownir import OwnIRError, build_sarif, check_facts, load

_REPO = os.path.join(os.path.dirname(__file__), "..")
_FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "ownir")


def _proto(**kw: object) -> Protocol:
    """The canonical test protocol: IsLoaded=false opens, IsLoaded=true closes,
    OnPropertyChanged(Document|Rows) is a barrier, OnPropertyChanged(IsBusy)
    is allowed."""
    base: dict[str, object] = {
        "name": "DocLoad",
        "opens": Matcher("assign", "IsLoaded", value=False),
        "closes": Matcher("assign", "IsLoaded", value=True),
        "barriers": (Matcher("call", "OnPropertyChanged",
                             args=frozenset({"Document", "Rows"})),),
        "allow": (Matcher("call", "OnPropertyChanged",
                          args=frozenset({"IsBusy", "IsLoaded"})),),
    }
    base.update(kw)
    return Protocol(**base)  # type: ignore[arg-type]


def _method(*events: object, name: str = "Ns.VM.Load") -> MethodEvents:
    return MethodEvents(name=name, file="VM.cs", events=tuple(events))  # type: ignore[arg-type]


_OPEN = AssignEv("IsLoaded", False, 10)
_CLOSE = AssignEv("IsLoaded", True, 90)
_NOTIFY_DOC = CallEv("OnPropertyChanged", "Document", 50)


def run() -> int:
    fails: list[str] = []
    checks = 0

    def check(cond: bool, msg: str) -> None:
        nonlocal checks
        checks += 1
        if not cond:
            fails.append(msg)

    def codes(vs: list[object]) -> list[tuple[str, bool, int]]:
        return [(v.kind, v.definite, v.line) for v in vs]  # type: ignore[attr-defined]

    # ---- 1. the core walk -------------------------------------------------

    # straight line: open -> barrier -> close = one definite barrier crossing.
    vs = check_protocols([_proto()], [_method(_OPEN, _NOTIFY_DOC, _CLOSE)])
    check(codes(vs) == [("barrier", True, 50)],
          f"open->barrier->close must be one definite crossing, got {vs}")
    check(vs and vs[0].open_line == 10, "provenance must point at the open site")
    check(vs and vs[0].close_line == 90, "the late close must be recorded as evidence")

    # the fixed twin: close before the barrier = silence.
    vs = check_protocols([_proto()], [_method(_OPEN, _CLOSE, _NOTIFY_DOC)])
    check(vs == [], f"close-before-barrier must be clean, got {vs}")

    # an allow-listed notification is safe while open.
    vs = check_protocols([_proto()], [_method(
        _OPEN, CallEv("OnPropertyChanged", "IsBusy", 20), _CLOSE)])
    check(vs == [], f"an allowed call while open must be clean, got {vs}")

    # an args-narrowed barrier does not match other args or an unknown arg.
    vs = check_protocols([_proto()], [_method(
        _OPEN, CallEv("OnPropertyChanged", "Totals", 20),
        CallEv("OnPropertyChanged", None, 21), _CLOSE)])
    check(vs == [], f"non-matching/unknown args must not cross, got {vs}")

    # a barrier hit in only one branch is still definite: the crossing path
    # carries a definitely-open state (the branch is where the flow goes, not
    # where the obligation becomes conditional).
    vs = check_protocols([_proto()], [_method(
        _OPEN, IfEv(20, then=(_NOTIFY_DOC,), orelse=()), _CLOSE)])
    check(codes(vs) == [("barrier", True, 50)],
          f"barrier inside a branch must stay definite, got {vs}")

    # closed in one branch only -> the barrier after the merge is a MAYBE.
    vs = check_protocols([_proto()], [_method(
        _OPEN,
        IfEv(20, then=(AssignEv("IsLoaded", True, 21),), orelse=()),
        CallEv("OnPropertyChanged", "Document", 30),
        AssignEv("IsLoaded", True, 40))])
    check(codes(vs) == [("barrier", False, 30)],
          f"half-closed at a merge must be a maybe crossing, got {vs}")

    # opened in one branch only -> also a maybe.
    vs = check_protocols([_proto()], [_method(
        IfEv(20, then=(_OPEN,), orelse=()),
        CallEv("OnPropertyChanged", "Document", 30))])
    got = codes(vs)
    check(("barrier", False, 30) in got,
          f"open-on-some-path must be a maybe crossing, got {vs}")

    # exit barriers: open with no close = leak off the end, anchored at the
    # open site (the OWN001 anchor-at-acquire precedent).
    vs = check_protocols([_proto()], [_method(_OPEN)])
    check(codes(vs) == [("exit", True, 10)],
          f"open falling off the end must be a definite exit leak, got {vs}")

    # an early return while open reports at the return line.
    vs = check_protocols([_proto()], [_method(
        _OPEN, IfEv(20, then=(ReturnEv(25),), orelse=()), _CLOSE)])
    check(codes(vs) == [("exit", True, 25)],
          f"early return while open must report at the return, got {vs}")

    # a throw while open reports at the throw line.
    vs = check_protocols([_proto()], [_method(_OPEN, ThrowEv(30))])
    check(codes(vs) == [("exit", True, 30)],
          f"throw while open must report at the throw, got {vs}")

    # the late-close hop belongs to barrier crossings only: an exit leak has
    # no barrier to be late for, even when a close exists later in the tree.
    vs = check_protocols([_proto()], [_method(
        _OPEN, IfEv(20, then=(ThrowEv(25),), orelse=()), _CLOSE)])
    check(codes(vs) == [("exit", True, 25)] and vs[0].close_line is None,
          f"an exit leak must not carry a late-close hop, got {vs}")

    # code after a return is on the other path only: close-after-early-return
    # still leaves the return-path leak, and only that.
    vs = check_protocols([_proto()], [_method(
        _OPEN, IfEv(20, then=(ReturnEv(25),), orelse=(_CLOSE,)))])
    check(codes(vs) == [("exit", True, 25)],
          f"only the returning path leaks, got {vs}")

    # exit_barriers=False silences exits but not barriers.
    vs = check_protocols([_proto(exit_barriers=False)], [_method(_OPEN)])
    check(vs == [], f"exit_barriers=false must silence the exit leak, got {vs}")

    # loops: close inside the body -> after the loop the state is {OPEN (0
    # iterations), CLOSED} -> a maybe crossing; and the loop emits ONCE.
    vs = check_protocols([_proto()], [_method(
        _OPEN,
        WhileEv(20, body=(AssignEv("IsLoaded", True, 21),)),
        CallEv("OnPropertyChanged", "Document", 30),
        AssignEv("IsLoaded", True, 40))])
    check(codes(vs) == [("barrier", False, 30)],
          f"loop may run zero times: barrier after it is a maybe, got {vs}")

    # a barrier inside a loop body while open: exactly one finding (the
    # fixpoint iterations are silent; only the converged pass emits).
    vs = check_protocols([_proto()], [_method(
        _OPEN, WhileEv(20, body=(_NOTIFY_DOC,)), _CLOSE)])
    check(codes(vs) == [("barrier", True, 50)],
          f"a barrier in a loop must report exactly once, got {vs}")

    # nested loops still emit once.
    vs = check_protocols([_proto()], [_method(
        _OPEN, WhileEv(20, body=(WhileEv(21, body=(_NOTIFY_DOC,)),)), _CLOSE)])
    check(codes(vs) == [("barrier", True, 50)],
          f"a barrier in a nested loop must report exactly once, got {vs}")

    # re-open inside a loop (close at the top of the body, re-open at the
    # bottom): the header join must reach a fixpoint, and the crossing stays
    # DEFINITE — every path (zero iterations or n) leaves the flag down.
    vs = check_protocols([_proto()], [_method(
        AssignEv("IsLoaded", False, 10),
        WhileEv(20, body=(AssignEv("IsLoaded", True, 21),
                          AssignEv("IsLoaded", False, 22))),
        CallEv("OnPropertyChanged", "Document", 30),
        AssignEv("IsLoaded", True, 40))])
    check(codes(vs) == [("barrier", True, 30)],
          f"open/close cycling in a loop must converge (and every path is "
          f"open at the barrier), got {vs}")

    # the opaque-write asymmetry: while OPEN an opaque write to the tracked
    # flag downgrades the crossing to a maybe (it may have closed)...
    vs = check_protocols([_proto()], [_method(
        _OPEN, AssignEv("IsLoaded", None, 20), _NOTIFY_DOC, _CLOSE)])
    check(codes(vs) == [("barrier", False, 50)],
          f"an opaque write may discharge -> maybe crossing, got {vs}")
    # ...but while CLOSED an opaque write must NOT invent an obligation.
    vs = check_protocols([_proto()], [_method(
        AssignEv("IsLoaded", None, 5), _NOTIFY_DOC)])
    check(vs == [], f"an opaque write must never open an obligation, got {vs}")
    # an opaque write to an untracked member is inert either way.
    vs = check_protocols([_proto()], [_method(
        _OPEN, AssignEv("Title", None, 20), _NOTIFY_DOC, _CLOSE)])
    check(codes(vs) == [("barrier", True, 50)],
          f"an untracked opaque write must not discharge, got {vs}")

    # a call the protocol does not name is neutral (no discharge, no crossing).
    vs = check_protocols([_proto()], [_method(
        _OPEN, CallEv("RebuildIndexes", None, 20), _NOTIFY_DOC, _CLOSE)])
    check(codes(vs) == [("barrier", True, 50)],
          f"an unnamed call must stay neutral, got {vs}")

    # call-based protocols: BeginUpdate/EndUpdate with a bare-call barrier.
    begin_end = Protocol(
        name="BatchUpdate",
        opens=Matcher("call", "BeginUpdate"),
        closes=Matcher("call", "EndUpdate"),
        barriers=(Matcher("call", "Refresh"),))
    vs = check_protocols([begin_end], [_method(
        CallEv("BeginUpdate", None, 10), CallEv("Refresh", None, 20),
        CallEv("EndUpdate", None, 30))])
    check(codes(vs) == [("barrier", True, 20)],
          f"call-open protocols must work, got {vs}")

    # two protocols are independent states over the same method.
    vs = check_protocols([_proto(), begin_end], [_method(
        _OPEN, CallEv("BeginUpdate", None, 20), CallEv("EndUpdate", None, 30),
        _NOTIFY_DOC, _CLOSE)])
    check(codes(vs) == [("barrier", True, 50)],
          f"protocols must not interfere, got {vs}")

    # scoping: exact and Type.Method-suffix match in, others out.
    scoped = _proto(methods=("VM.Load",))
    vs = check_protocols([scoped], [_method(_OPEN, _NOTIFY_DOC, _CLOSE)])
    check(len(vs) == 1, f"a Type.Method suffix must match Ns.VM.Load, got {vs}")
    vs = check_protocols([scoped], [
        _method(_OPEN, _NOTIFY_DOC, _CLOSE, name="Ns.VM.LoadAll"),
        _method(_OPEN, _NOTIFY_DOC, _CLOSE, name="Ns.OtherVM.Load2")])
    check(vs == [], f"out-of-scope methods must stay silent, got {vs}")
    check([p.name for p in unmatched_scopes(
        [scoped], [_method(_OPEN, name="Ns.OtherVM.Reload")])] == ["DocLoad"],
        "a scope matching nothing must surface as a dead rule")
    check(unmatched_scopes([_proto()], []) == [],
          "an unscoped protocol is never a dead rule")

    # determinism: findings sorted by (file, line, protocol).
    vs = check_protocols([_proto()], [_method(
        _OPEN, _NOTIFY_DOC, CallEv("OnPropertyChanged", "Rows", 60), _CLOSE)])
    check([v.line for v in vs] == [50, 60], f"findings must be ordered, got {vs}")

    # ---- 2. parsing: fail-loud vocabulary ---------------------------------

    def rejects(fn: object, raw: object, why: str) -> None:
        nonlocal checks
        checks += 1
        try:
            fn(raw)  # type: ignore[operator]
            fails.append(f"{why}: not rejected")
        except ProtocolFactsError:
            pass

    rejects(parse_protocol, {"name": "P"}, "opens/closes are required")
    rejects(parse_protocol,
            {"name": "P", "opens": {"kind": "flip", "target": "x"},
             "closes": {"kind": "assign", "target": "x", "value": True}},
            "an unknown matcher kind")
    rejects(parse_protocol,
            {"name": "P", "opens": {"kind": "assign", "target": "x"},
             "closes": {"kind": "assign", "target": "x", "value": True}},
            "an opens assign matcher without a value")
    rejects(parse_protocol,
            {"name": "P", "opens": {"kind": "assign", "target": "x", "value": False},
             "closes": {"kind": "assign", "target": "x", "value": True},
             "exit_barriers": False},
            "no barriers and no exit barriers (a rule that cannot fire)")
    rejects(parse_protocol,
            {"name": "P", "opens": {"kind": "call", "callee": "BeginUpdate"},
             "closes": {"kind": "call", "callee": "EndUpdate"},
             "barriers": [{"kind": "call", "callee": "BeginUpdate"}]},
            "a barrier equal to opens (shadowed, silently dead)")
    rejects(parse_method, {"name": "m", "events": [{"ev": "goto", "line": 1}]},
            "an unknown protocol event")
    rejects(parse_method, {"name": "m", "events": [{"ev": "assign", "line": 1}]},
            "an assign event without a target")
    rejects(parse_method,
            {"name": "m", "events": [{"ev": "assign", "target": "x", "value": 1,
                                      "line": 1}]},
            "a non-boolean assign value (the bool-is-int trap)")
    checks += 1
    try:
        parse_events([{"ev": "if", "then": [{"ev": "nope"}], "else": []}], "t")
        fails.append("an unknown ev nested under if/then was not rejected")
    except ProtocolFactsError:
        pass

    # ---- 3. the bridge: fixtures end-to-end -------------------------------

    with open(os.path.join(_FIXTURES, "protocol_isloaded_violation.facts.json"),
              encoding="utf-8") as f:
        bad = json.load(f)
    findings = check_facts(bad)
    check(len(findings) == 1, f"the killer fixture must yield exactly one finding, "
                              f"got {[(x.code, x.line) for x in findings]}")
    if findings:
        f0 = findings[0]
        check(f0.code == "OBL001" and f0.file == "BigDocumentViewModel.cs"
              and f0.line == 241,
              f"expected OBL001 at BigDocumentViewModel.cs:241, got "
              f"{f0.code} at {f0.file}:{f0.line}")
        check(f0.component == "BigDocumentViewModel"
              and f0.event == "DocumentLoading"
              and f0.handler == "LoadBigDocument",
              f"finding identity fields drifted: {f0.component}/{f0.event}/{f0.handler}")
        check(f0.kind == "protocol obligation" and not f0.advisory,
              "an OBL001 is an error-tier protocol-obligation verdict")
        # the evidence slice: opened -> barrier -> closed-late, in order.
        check([ln for (_, ln, _) in f0.flow] == [184, 241, 260],
              f"evidence slice must be open->barrier->late-close, got {f0.flow}")
        # messages are line-free (OwnAudit fingerprints on path|rule|message).
        check(not any(ch.isdigit() for ch in f0.message.replace("IsLoaded", "")),
              f"the message must not embed line numbers: {f0.message!r}")
        check("IsLoaded = true" in f0.message and "OnPropertyChanged(Document)"
              in f0.message, f"the message must name the fix and the barrier: "
                             f"{f0.message!r}")

    with open(os.path.join(_FIXTURES, "protocol_isloaded_clean.facts.json"),
              encoding="utf-8") as f:
        good = json.load(f)
    clean = check_facts(good)
    check(clean == [], f"the fixed twin must be silent, got "
                       f"{[(x.code, x.line) for x in clean]}")

    # exit leak through the bridge: OBL003 anchored at the open site, and the
    # SARIF rules catalogue knows the code.
    leak = check_facts({
        "ownir_version": 0, "module": "S",
        "protocols": [{
            "name": "Suppress",
            "opens": {"kind": "assign", "target": "_suppress", "value": True},
            "closes": {"kind": "assign", "target": "_suppress", "value": False}}],
        "protocol_functions": [{
            "name": "VM.Batch", "file": "VM.cs", "events": [
                {"ev": "assign", "target": "_suppress", "value": True, "line": 7},
                {"ev": "if", "line": 8,
                 "then": [{"ev": "throw", "line": 9}], "else": []},
                {"ev": "assign", "target": "_suppress", "value": False,
                 "line": 12}]}]})
    check([(x.code, x.line) for x in leak] == [("OBL003", 9)],
          f"a throw while open must be OBL003 at the throw, got "
          f"{[(x.code, x.line) for x in leak]}")
    sarif = build_sarif(leak)
    rules = {r["id"]: r["shortDescription"]["text"]
             for r in sarif["runs"][0]["tool"]["driver"]["rules"]}
    check("OBL003" in rules, "OBL003 must reach the SARIF rules catalogue")

    # OBL005: a scoped protocol matching no reported method is an advisory.
    dead = check_facts({
        "ownir_version": 0, "module": "S",
        "protocols": [{
            "name": "Ghost",
            "opens": {"kind": "assign", "target": "x", "value": False},
            "closes": {"kind": "assign", "target": "x", "value": True},
            "scope": {"methods": ["VM.Misspelled"]}}],
        "protocol_functions": [{"name": "VM.Load", "file": "VM.cs",
                                "events": []}]})
    check([(x.code, x.advisory) for x in dead] == [("OBL005", True)],
          f"a dead scope must be the OBL005 advisory, got "
          f"{[(x.code, x.advisory) for x in dead]}")

    # malformed blocks degrade gracefully on the direct check_facts path
    # (load() fail-louds; embedders/tests may skip it).
    check(check_facts({"ownir_version": 0, "components": [],
                       "protocols": "nope"}) == [],
          "a malformed protocols block must not crash check_facts")
    check(check_facts({"ownir_version": 0, "components": [],
                       "protocols": [{"name": "P"}],
                       "protocol_functions": [{"name": "m"}]}) == [],
          "a malformed protocol entry is skipped on the direct path")

    # duplicate protocol names: the name is the identity findings map back by.
    # On the direct path the first wins deterministically (the second is
    # skipped — never a mixed message or a dedup-collapsed pair of findings)...
    dup = check_facts({
        "ownir_version": 0, "module": "S",
        "protocols": [
            {"name": "Dup",
             "opens": {"kind": "assign", "target": "A", "value": False},
             "closes": {"kind": "assign", "target": "A", "value": True},
             "barriers": [{"kind": "call", "callee": "Notify"}]},
            {"name": "Dup",
             "opens": {"kind": "call", "callee": "BeginUpdate"},
             "closes": {"kind": "call", "callee": "EndUpdate"},
             "barriers": [{"kind": "call", "callee": "Notify"}]}],
        "protocol_functions": [{"name": "VM.Go", "file": "VM.cs", "events": [
            {"ev": "assign", "target": "A", "value": False, "line": 10},
            {"ev": "call", "callee": "BeginUpdate", "line": 11},
            {"ev": "call", "callee": "Notify", "line": 20},
            {"ev": "assign", "target": "A", "value": True, "line": 30},
            {"ev": "call", "callee": "EndUpdate", "line": 31}]}]})
    check([(x.code, x.line) for x in dup] == [("OBL001", 20)]
          and dup and "A = true" in dup[0].message,
          f"duplicate names: first must win whole, got "
          f"{[(x.code, x.message) for x in dup]}")

    # load() is the fail-loud gate: an unknown ev is rejected with OwnIRError,
    # and so is a duplicate protocol name (ambiguous identity).
    def load_rejects(doc: dict[str, object], why: str) -> None:
        nonlocal checks
        with tempfile.NamedTemporaryFile("w", suffix=".facts.json", delete=False,
                                         encoding="utf-8") as tf:
            json.dump(doc, tf)
            tmp = tf.name
        checks += 1
        try:
            load(tmp)
            fails.append(f"load() accepted {why}")
        except OwnIRError:
            pass
        finally:
            os.unlink(tmp)

    load_rejects({"ownir_version": 0, "module": "S",
                  "protocol_functions": [{"name": "m", "events":
                                          [{"ev": "goto", "line": 1}]}]},
                 "an unknown protocol event")
    _p = {"name": "Dup",
          "opens": {"kind": "assign", "target": "A", "value": False},
          "closes": {"kind": "assign", "target": "A", "value": True}}
    load_rejects({"ownir_version": 0, "module": "S", "protocols": [_p, dict(_p)]},
                 "a duplicate protocol name")

    # both fixtures pass the real load() gate (shape-valid on disk).
    for fx in ("protocol_isloaded_violation", "protocol_isloaded_clean"):
        checks += 1
        try:
            load(os.path.join(_FIXTURES, f"{fx}.facts.json"))
        except OwnIRError as e:
            fails.append(f"fixture {fx} rejected by load(): {e}")

    # ---- 4. schema <-> code binding (the flow-op discipline, spec §8) -----

    with open(os.path.join(_REPO, "spec", "ownir.schema.json"),
              encoding="utf-8") as f:
        schema = json.load(f)
    defs = schema.get("$defs", {})
    for prop in ("protocols", "protocol_functions"):
        check(prop in schema.get("properties", {}),
              f"schema must declare the top-level '{prop}' block")
    evs = [b.get("properties", {}).get("ev", {}).get("const")
           for b in defs.get("protocolEvent", {}).get("oneOf", [])]
    check(None not in evs and len(evs) == len(set(evs)),
          f"schema protocolEvent consts malformed: {evs}")
    check(set(evs) == set(EVENT_KINDS),
          f"schema protocolEvent consts {sorted(x for x in evs if x)} != code "
          f"EVENT_KINDS {sorted(EVENT_KINDS)} — vocabulary drift")
    kinds = [b.get("properties", {}).get("kind", {}).get("const")
             for b in defs.get("protocolMatcher", {}).get("oneOf", [])]
    check(set(kinds) == set(MATCHER_KINDS),
          f"schema protocolMatcher consts {sorted(x for x in kinds if x)} != "
          f"code MATCHER_KINDS {sorted(MATCHER_KINDS)} — vocabulary drift")
    # the opens/closes variant must exist and require `value` on its assign
    # branch (the require_value rule, structurally enforced in the schema).
    oc = defs.get("protocolOpenClose", {}).get("oneOf", [])
    check({b.get("properties", {}).get("kind", {}).get("const")
           for b in oc} == set(MATCHER_KINDS),
          "schema protocolOpenClose must cover the matcher vocabulary")
    oc_assign = next((b for b in oc
                      if b.get("properties", {}).get("kind", {}).get("const")
                      == "assign"), {})
    check("value" in oc_assign.get("required", []),
          "schema protocolOpenClose assign branch must require 'value'")
    # drive every declared ev through the parser: a phantom set entry
    # (declared but unparseable) reddens this, mirroring the flow-op check.
    for ev in sorted(EVENT_KINDS):
        node: dict[str, object] = {"ev": ev, "line": 1}
        if ev == "assign":
            node["target"] = "x"
        if ev == "call":
            node["callee"] = "f"
        checks += 1
        try:
            parse_events([node], "pin")
        except ProtocolFactsError as e:
            fails.append(f"EVENT_KINDS lists {ev!r} but parse_events rejects it: {e}")

    for msg in fails:
        print(f"OBLIGATIONS FAIL: {msg}")
    print(f"obligations: {checks - len(fails)}/{checks} protocol checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
