#!/usr/bin/env python3
"""
OwnIR fact-bridge tests (P-001 v0).

The locally-testable half of the C#-extraction pipeline: given OwnIR facts (as a
Roslyn extractor would emit), the bridge must route them through the existing
core and surface a finding at the original C# location for an unreleased
subscription — and stay silent for a released one.

The Roslyn extractor itself (frontend/roslyn/) needs dotnet and is validated in
CI; here we feed hand-written facts so the bridge + core path is pinned with no
dotnet dependency.

Run:  python tests/test_ownir.py
      python tests/run_tests.py     (runs it as part of the suite)
"""

from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tempfile

from ownlang.di import LIFETIMES as DI_LIFETIMES
from ownlang.diagnostics import TITLES
from ownlang.ownir import (
    _FLOW_OPS,
    _KNOWN_RESOURCE_KINDS,
    _PARAM_EFFECTS,
    OWNIR_VERSION,
    Finding,
    OwnIRError,
    build_sarif,
    check_facts,
    load,
    render_finding,
    to_own,
)
from ownlang.parser import parse

_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "ownir",
                        "sample.facts.json")
_TIMER_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "ownir",
                              "timer.facts.json")
_DISPOSABLE_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                                   "ownir", "disposable.facts.json")
_SUBSCRIBE_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                                  "ownir", "subscribe.facts.json")
_POOL_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                             "ownir", "pool.facts.json")
_LOCAL_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                              "ownir", "local_disposable.facts.json")
_UOW_FLOW_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                                 "ownir", "unitofwork_flow.facts.json")
_LEAK_ON_ELSE_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                                     "ownir", "flow_leak_on_else.facts.json")
_WHILE_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                              "ownir", "flow_while.facts.json")
_TWO_EXITS_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                                  "ownir", "flow_leak_two_exits.facts.json")
_NESTED_THROW_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                                     "ownir", "flow_nested_throw.facts.json")
_FINALLY_SWITCH_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                                       "ownir", "flow_finally_switch.facts.json")
_POOL_PARTIAL_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                                     "ownir", "flow_pool_partial.facts.json")
_DI_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                           "ownir", "di.facts.json")
_UNRESOLVED_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                                   "ownir", "unresolved.facts.json")
_CAPTURE_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                                "ownir", "capture.facts.json")
_DI_CAPTURE_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                                   "ownir", "di_capture.facts.json")
_HANDOFF_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                                "ownir", "handoff_contract.facts.json")
_INFER_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                              "ownir", "contract_inference.facts.json")


def _write_facts(obj: dict) -> str:
    """Write a facts dict to a temp file and return its path (load() needs one)."""
    fd, path = tempfile.mkstemp(suffix=".facts.json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    return path


def _load_raises(obj: dict) -> bool:
    try:
        load(_write_facts(obj))
    except OwnIRError:
        return True
    return False


def run() -> int:
    """Pin the OwnIR bridge on the canonical leak/ok facts; return 0/1."""
    fails: list[str] = []
    checks = 0

    with open(_FIXTURE, encoding="utf-8") as f:
        facts = json.load(f)

    # the lowered sketch must be valid .own (it goes through the real parser).
    src, _ = to_own(facts)
    checks += 1
    try:
        parse(src)
    except Exception as e:
        fails.append(f"lowered facts do not parse: {e}")

    findings = check_facts(facts)

    # exactly one finding: the unreleased CustomerViewModel subscription.
    checks += 1
    if len(findings) != 1:
        fails.append(f"expected 1 finding, got {len(findings)}: "
                     f"{[ (x.file, x.line, x.code) for x in findings ]}")
    else:
        f0 = findings[0]
        checks += 1
        if (f0.file, f0.line, f0.code) != ("CustomerViewModel.cs", 12, "OWN001"):
            fails.append(f"wrong location/code: {f0.file}:{f0.line} {f0.code}")
        if "CustomerChanged" not in f0.message or "leak" not in f0.message:
            fails.append(f"message missing event/leak: {f0.message!r}")
        if "[resource: subscription token]" not in f0.render():
            fails.append("rendered finding missing kind tag")

    # a released subscription (OrdersViewModel) must NOT be reported.
    checks += 1
    if any(x.component == "OrdersViewModel" for x in findings):
        fails.append("released subscription was wrongly reported")

    # an empty facts set yields nothing and does not crash.
    checks += 1
    if check_facts({"module": "Empty", "components": []}):
        fails.append("empty facts produced findings")

    # --- P-004 severity tiering: the subscription fact's `source` grades severity.
    def _one(source: str, lambda_: bool = False) -> Finding:
        """One unreleased subscription with the given source kind -> its Finding."""
        return check_facts({"module": "M", "components": [
            {"name": "Vm", "file": "Vm.cs", "subscriptions": [
                {"event": "bus.X", "handler": "h", "line": 5, "released": False,
                 "resource": "subscription", "source": source,
                 "lambda": lambda_}]}]})[0]

    # an injected source (unknown lifetime) is a WARNING-tier leak — not a hard
    # error — and says so; it is still a leak verdict (not advisory) so it keeps
    # the non-zero exit code.
    checks += 1
    inj = _one("injected")
    if inj.severity != "warning":
        fails.append(f"injected source should be warning-tier, got {inj.severity!r}")
    if inj.advisory:
        fails.append("injected-source leak must not be advisory (still a leak)")
    if "injected dependency" not in inj.message:
        fails.append(f"injected message missing wording: {inj.message!r}")

    # a static event source is provably process-lived -> a hard ERROR: its severity
    # field is None, so it renders at the host's --severity (default error). (The
    # field is the core's verdict; the cmd_ownir render policy is locked in CI.)
    checks += 1
    stat = _one("static")
    if stat.severity is not None:
        fails.append(f"static source should be error-tier (None), got {stat.severity!r}")
    if "injected dependency" in stat.message:
        fails.append(f"static message must not claim an injected source: {stat.message!r}")

    # a lambda handler additionally calls out that it has no `-=` handle to detach.
    checks += 1
    lam = _one("injected", lambda_=True)
    if lam.severity != "warning":
        fails.append(f"injected lambda should be warning-tier, got {lam.severity!r}")
    if "inline lambda" not in lam.message or "-=" not in lam.message:
        fails.append(f"lambda handler should note the missing -= handle: {lam.message!r}")

    # --- #146: interprocedural publisher provenance. An injected `+=` whose
    #     publisher is proven "constructed-and-returned" by EVERY in-compilation
    #     caller (the extractor's compilation-wide pass stamps
    #     `source_provenance: "returned_fresh"`) is bounded by the returned
    #     publisher's lifetime -> SILENT, like a locally-constructed source (the
    #     Newtonsoft `JsonSerializer.Create` -> `ApplySerializerSettings` shape).
    #     Precision-first: only the exact vocabulary value routes; anything else
    #     keeps the honest OWN001 warning.
    def _prov(provenance: str | None, source_type: str | None = None,
              services: list[dict[str, object]] | None = None) -> list[Finding]:
        s: dict[str, object] = {
            "event": "serializer.Error", "handler": "settings.Error", "line": 9,
            "released": False, "resource": "subscription", "source": "injected"}
        if provenance is not None:
            s["source_provenance"] = provenance
        if source_type is not None:
            s["source_type"] = source_type
        pfacts: dict[str, object] = {"module": "M", "components": [
            {"name": "SerializerFactory", "file": "F.cs", "subscriptions": [s]}]}
        if services is not None:
            pfacts["services"] = services
        return check_facts(pfacts)

    # proven returned-fresh publisher -> silent.
    checks += 1
    if _prov("returned_fresh"):
        fails.append(f"returned-fresh publisher should be silent, got "
                     f"{[(x.code, x.severity) for x in _prov('returned_fresh')]}")
    # an UNKNOWN provenance value never silences — the honest warning stays.
    checks += 1
    if [(x.code, x.severity) for x in _prov("hearsay")] != [("OWN001", "warning")]:
        fails.append(f"unknown provenance must keep the OWN001 warning, got "
                     f"{[(x.code, x.severity) for x in _prov('hearsay')]}")
    # premise guard: WITHOUT provenance, a singleton-registered source_type
    # escalates through the DI hop to OWN014 (the type-level path this test
    # pits the instance-level fact against).
    _prov_svcs: list[dict[str, object]] = [
        {"name": "IEventBus", "lifetime": "singleton", "file": "S.cs", "line": 3}]
    checks += 1
    if [x.code for x in _prov(None, "IEventBus", _prov_svcs)] != ["OWN014"]:
        fails.append(f"premise: singleton-typed injected source should escalate "
                     f"to OWN014, got "
                     f"{[x.code for x in _prov(None, 'IEventBus', _prov_svcs)]}")
    # instance-level provenance BEATS the type-level DI hop: even with the
    # publisher's type registered as a singleton, THIS publisher was freshly
    # constructed by the caller, not resolved from the container -> silent.
    checks += 1
    if _prov("returned_fresh", "IEventBus", _prov_svcs):
        fails.append(
            f"returned-fresh must beat the DI singleton escalation, got "
            f"{[(x.code, x.severity) for x in _prov('returned_fresh', 'IEventBus', _prov_svcs)]}")
    # the lowered sketch still parses with a provenance-skipped record present.
    checks += 1
    try:
        parse(to_own({"module": "M", "components": [
            {"name": "F", "file": "F.cs", "subscriptions": [
                {"event": "s.E", "handler": "h", "line": 2, "released": False,
                 "resource": "subscription", "source": "injected",
                 "source_provenance": "returned_fresh"}]}]})[0])
    except Exception as e:
        fails.append(f"provenance-skipped facts do not lower/parse: {e}")
    # load() validates the field's type (additive optional, but never garbage).
    checks += 1
    if not _load_raises({"ownir_version": OWNIR_VERSION, "module": "M",
                         "components": [{"name": "F", "file": "F.cs",
                                         "subscriptions": [
                                             {"event": "e", "line": 1,
                                              "source_provenance": 7}]}]}):
        fails.append("non-string source_provenance was accepted "
                     "(should raise OwnIRError)")

    # --- P-004 source-lifetime tiering for `subscribe` (ignored `.Subscribe()`
    #     result) — the WalletWasabi precision win. A SELF-rooted subscribe
    #     (`this.WhenAnyValue(x => x.SelfProp)`) is a GC-collectible self-cycle ->
    #     silent (not a leak); an `injected` source -> warning (unknown lifetime);
    #     a `static`/external/unannotated source -> a leak (error). Mirrors `+=`.
    def _sub(source: str | None) -> list[Finding]:
        s: dict[str, object] = {
            "event": "this.WhenAnyValue(x => x.Foo).Subscribe", "handler": "",
            "line": 7, "released": False, "resource": "subscribe"}
        if source is not None:
            s["source"] = source
        return check_facts({"module": "M", "components": [
            {"name": "Vm", "file": "Vm.cs", "subscriptions": [s]}]})

    # self-rooted -> silent (the cycle the GC collects); the 118->real win.
    checks += 1
    if _sub("self"):
        fails.append(f"a self-rooted subscribe must be silent (self-cycle), got "
                     f"{[(x.code, x.severity) for x in _sub('self')]}")
    # injected source -> OWN001 WARNING (unknown lifetime, may outlive).
    checks += 1
    si = _sub("injected")
    if [(x.code, x.severity) for x in si] != [("OWN001", "warning")]:
        fails.append(f"injected subscribe should be an OWN001 warning, got "
                     f"{[(x.code, x.severity) for x in si]}")
    elif "may outlive" not in si[0].message:
        fails.append(f"injected subscribe message missing wording: {si[0].message!r}")
    # external (static) and UNANNOTATED -> OWN001 error (unchanged — no regression).
    checks += 1
    for src in ("static", None):
        se = _sub(src)
        if [(x.code, x.severity) for x in se] != [("OWN001", None)]:
            fails.append(f"subscribe source={src!r} should stay an OWN001 error, "
                         f"got {[(x.code, x.severity) for x in se]}")

    # the fixture carries the current schema version (the contract is stamped).
    checks += 1
    if facts.get("ownir_version") != OWNIR_VERSION:
        fails.append("fixture is missing the current ownir_version stamp")

    # a future/foreign schema version must fail loudly at load, not be misread.
    checks += 1
    bad = {"ownir_version": OWNIR_VERSION + 1, "module": "Future", "components": []}
    if not _load_raises(bad):
        fails.append("mismatched ownir_version did not raise OwnIRError")

    # an omitted version is accepted as the current one (legacy v0 producers).
    checks += 1
    try:
        load(_write_facts({"module": "Legacy", "components": []}))
    except OwnIRError as e:
        fails.append(f"versionless facts wrongly rejected: {e}")

    # an unknown flow op (a newer extractor emitting a vocabulary the core can't
    # lower) must RAISE, not be silently dropped — else the acquire/release facts
    # nested inside it vanish and verdicts flip with every fixture still green.
    checks += 1
    unknown_op = {"ownir_version": OWNIR_VERSION, "module": "X", "components": [],
                  "functions": [{"name": "F", "file": "F.cs", "body": [
                      {"op": "acquire", "var": "c", "line": 1},
                      {"op": "try", "line": 2, "body": [
                          {"op": "release", "var": "c", "line": 3}]}]}]}
    try:
        check_facts(unknown_op)
        fails.append("unknown flow op was silently accepted (should raise OwnIRError)")
    except OwnIRError:
        pass

    # A present-but-unknown resource kind changes routing (§4), so load must reject
    # it (fail-loud) rather than fall through to the subscription path and
    # mis-classify. An ABSENT `resource` field still defaults to subscription.
    checks += 1
    bad_kind = {"ownir_version": OWNIR_VERSION, "module": "X",
                "components": [{"name": "C", "file": "C.cs", "subscriptions": [
                    {"event": "e", "line": 1, "resource": "mutex"}]}]}
    if not _load_raises(bad_kind):
        fails.append("present-but-unknown resource kind was accepted (should raise OwnIRError)")
    checks += 1
    ok_absent = {"ownir_version": OWNIR_VERSION, "module": "X",
                 "components": [{"name": "C", "file": "C.cs", "subscriptions": [
                     {"event": "e", "line": 1}]}]}  # no `resource` -> defaults to subscription
    if _load_raises(ok_absent):
        fails.append("an absent resource field was wrongly rejected (must default to subscription)")

    # Version single-sourcing (IR2): every producer must stamp the SAME
    # ownir_version as the core. The literal is hand-kept in each frontend today —
    # once P-022's `own-ir` crate lands there are FOUR producers, so a schema will
    # make this a generated constant (spec/OwnIR.md §2). Until then, assert the
    # frontends match the core here, so "bumped the core, forgot a frontend" (or the
    # reverse) fails loudly instead of silently mis-reading facts at runtime.
    _ver = re.compile(r'ownir_version["\s]*[=:]\s*(\d+)')
    _repo = os.path.join(os.path.dirname(__file__), "..")
    _producers = {
        "Roslyn extractor (Program.cs)":
            os.path.join(_repo, "frontend", "roslyn", "OwnSharp.Extractor", "Program.cs"),
        "OwnTS frontend (ownts.py)":
            os.path.join(_repo, "frontend", "ownts", "ownts.py"),
    }
    for _label, _path in _producers.items():
        checks += 1
        try:
            with open(_path, encoding="utf-8") as _f:
                _m = _ver.search(_f.read())
        except OSError as _e:
            fails.append(f"{_label}: cannot read producer ({_e})")
            continue
        if _m is None:
            fails.append(f"{_label}: no `ownir_version` literal found (moved? update this check)")
        elif int(_m.group(1)) != OWNIR_VERSION:
            fails.append(f"{_label}: ownir_version {_m.group(1)} != core OWNIR_VERSION "
                         f"{OWNIR_VERSION} — bump every producer together")

    # --- Schema <-> code binding (spec/ownir.schema.json). The JSON Schema is the
    #     single source the Python core and the Rust `own-ir` crate (P-022) are both
    #     checked against, but the core cannot import a jsonschema validator (the
    #     zero-dependency constraint). So instead of validating documents against the
    #     schema, we pin the schema's *vocabulary* to the code's authoritative sets:
    #     the enums and the version const cannot drift out from under the validator
    #     (ownlang/ownir.py::load) without reddening this build. When the schema grows
    #     a new enum value the code doesn't know — or vice-versa — this fires.
    _schema_path = os.path.join(_repo, "spec", "ownir.schema.json")
    checks += 1
    try:
        with open(_schema_path, encoding="utf-8") as _f:
            _schema = json.load(_f)
    except (OSError, json.JSONDecodeError) as _e:
        fails.append(f"spec/ownir.schema.json unreadable/invalid: {_e}")
        _schema = None
    if _schema is not None:
        _defs = _schema.get("$defs", {})
        # 1) ownir_version const == core OWNIR_VERSION
        checks += 1
        _sv = _schema.get("properties", {}).get("ownir_version", {}).get("const")
        if _sv != OWNIR_VERSION:
            fails.append(f"schema ownir_version const {_sv!r} != core OWNIR_VERSION "
                         f"{OWNIR_VERSION}")
        # 2) resourceKind enum == _KNOWN_RESOURCE_KINDS (the load() routing authority)
        checks += 1
        _sk = set(_defs.get("resourceKind", {}).get("enum", []))
        if _sk != set(_KNOWN_RESOURCE_KINDS):
            fails.append(f"schema resourceKind enum {sorted(_sk)} != code "
                         f"_KNOWN_RESOURCE_KINDS {sorted(_KNOWN_RESOURCE_KINDS)}")
        # 3) diLifetime enum == di.LIFETIMES (the service-lifetime authority)
        checks += 1
        _sl = set(_defs.get("diLifetime", {}).get("enum", []))
        if _sl != set(DI_LIFETIMES):
            fails.append(f"schema diLifetime enum {sorted(_sl)} != code "
                         f"di.LIFETIMES {sorted(DI_LIFETIMES)}")
        # 3b) paramEffect enum == _PARAM_EFFECTS (the load() contract-effect authority)
        checks += 1
        _se = set(_defs.get("paramEffect", {}).get("enum", []))
        if _se != set(_PARAM_EFFECTS):
            fails.append(f"schema paramEffect enum {sorted(_se)} != code "
                         f"_PARAM_EFFECTS {sorted(_PARAM_EFFECTS)}")
        # 4) flowOp discriminator consts. `_FLOW_OPS` is the lowerer's authoritative
        #    op set (the _lower_flow `else` rejects anything outside it as vocabulary
        #    skew). Bind the schema to it BOTH ways: (a) the schema's oneOf consts must
        #    EQUAL _FLOW_OPS — so a handled op the schema forgot, or a schema op the
        #    lowerer never gained, both redden this; and (b) drive every op through the
        #    lowerer so a phantom set entry (declared but unlowered) still fails. The
        #    two together close the direction Codex flagged: the schema cannot lag the
        #    lowerer's op vocabulary.
        _ops = [b.get("properties", {}).get("op", {}).get("const")
                for b in _defs.get("flowOp", {}).get("oneOf", [])]
        checks += 1
        if None in _ops or len(_ops) != len(set(_ops)):
            fails.append(f"schema flowOp oneOf has missing/duplicate op consts: {_ops}")
        checks += 1
        if set(_ops) != set(_FLOW_OPS):
            fails.append(f"schema flowOp consts {sorted(x for x in _ops if x)} != code "
                         f"_FLOW_OPS {sorted(_FLOW_OPS)} — op-vocabulary drift")
        for _op in sorted(_FLOW_OPS):
            checks += 1
            # a minimal, self-consistent body for each op (compound ops carry empty
            # sub-bodies; value ops carry a var/callee). A declared op that fails to
            # lower (unknown-op OR the declared-but-unhandled internal raise) is a
            # phantom authority entry — the set claims an op the lowerer cannot handle.
            _node = {"op": _op, "line": 1}
            if _op in ("acquire", "release", "use", "overspan", "alias_join"):
                _node["var"] = "x"
            if _op == "alias_join":
                _node["src"] = "x"
            if _op == "call":
                _node["callee"] = "f"
            _facts = {"ownir_version": OWNIR_VERSION, "module": "S",
                      "functions": [{"name": "m", "file": "m.cs", "body": [_node]}]}
            try:
                check_facts(_facts)
            except OwnIRError as _e:
                if ("unknown OwnIR flow op" in str(_e)
                        or "no lowering in _lower_flow" in str(_e)):
                    fails.append(f"_FLOW_OPS lists {_op!r} but _lower_flow does not "
                                 f"handle it ({_e})")
        # the guard is live: an op NOT in _FLOW_OPS is rejected as unknown vocabulary
        #    (the raise fires during lowering, so drive it through check_facts).
        checks += 1
        _bogus = {"ownir_version": OWNIR_VERSION, "module": "S",
                  "functions": [{"name": "m", "file": "m.cs",
                                 "body": [{"op": "try", "line": 1}]}]}
        try:
            check_facts(_bogus)
            fails.append("an unknown flow op ('try') was not rejected — fail-loud guard dead")
        except OwnIRError:
            pass

    # --- WPF002 timer profile: a started timer never stopped/detached leaks,
    #     a stopped one stays silent, and the finding is tagged [resource: timer].
    with open(_TIMER_FIXTURE, encoding="utf-8") as f:
        tfacts = json.load(f)
    tfindings = check_facts(tfacts)
    checks += 1
    leaks = [x for x in tfindings if x.component == "TimerViewModel"]
    if len(tfindings) != 1 or not leaks:
        fails.append(f"expected 1 timer finding (TimerViewModel), got "
                     f"{[(x.component, x.code) for x in tfindings]}")
    else:
        t0 = leaks[0]
        checks += 1
        if (t0.file, t0.line, t0.code) != ("TimerViewModel.cs", 15, "OWN001"):
            fails.append(f"wrong timer location/code: {t0.file}:{t0.line} {t0.code}")
        if "timer" not in t0.message or "stopped" not in t0.message:
            fails.append(f"timer message missing timer/stopped: {t0.message!r}")
        if "[resource: timer]" not in t0.render():
            fails.append(f"timer finding missing kind tag: {t0.render()!r}")
    # a stopped timer (released) must NOT be reported.
    checks += 1
    if any(x.component == "CleanTimerViewModel" for x in tfindings):
        fails.append("stopped timer was wrongly reported")

    # --- WPF003 IDisposable field: a field the class new's and never disposes
    #     leaks; one disposed in Dispose() stays silent; tag [resource: disposable field].
    with open(_DISPOSABLE_FIXTURE, encoding="utf-8") as f:
        dfacts = json.load(f)
    dfindings = check_facts(dfacts)
    checks += 1
    dleaks = [x for x in dfindings if x.component == "ReportViewModel"]
    if len(dfindings) != 1 or not dleaks:
        fails.append(f"expected 1 disposable finding (ReportViewModel), got "
                     f"{[(x.component, x.code) for x in dfindings]}")
    else:
        d0 = dleaks[0]
        checks += 1
        if (d0.file, d0.line, d0.code) != ("DisposableFieldViewModel.cs", 10, "OWN001"):
            fails.append(f"wrong field location/code: {d0.file}:{d0.line} {d0.code}")
        if "IDisposable field" not in d0.message or "_cts" not in d0.message:
            fails.append(f"disposable message missing field: {d0.message!r}")
        if "CancellationTokenSource" not in d0.message:
            fails.append(f"disposable message missing type: {d0.message!r}")
        if "[resource: disposable field]" not in d0.render():
            fails.append(f"disposable finding missing kind tag: {d0.render()!r}")
    # a field disposed in Dispose() (released) must NOT be reported.
    checks += 1
    if any(x.component == "CleanReportViewModel" for x in dfindings):
        fails.append("disposed field was wrongly reported")

    # --- WPF004 ignored Subscribe(): the dropped IDisposable token always leaks,
    #     carrying the [resource: subscription token] tag.
    with open(_SUBSCRIBE_FIXTURE, encoding="utf-8") as f:
        sfacts = json.load(f)
    sfindings = check_facts(sfacts)
    checks += 1
    if len(sfindings) != 1:
        fails.append(f"expected 1 subscribe finding, got "
                     f"{[(x.component, x.code) for x in sfindings]}")
    else:
        s0 = sfindings[0]
        checks += 1
        if (s0.file, s0.line, s0.code) != ("MessengerViewModel.cs", 12, "OWN001"):
            fails.append(f"wrong subscribe location/code: {s0.file}:{s0.line} {s0.code}")
        if "ignored" not in s0.message or "Subscribe" not in s0.message:
            fails.append(f"subscribe message missing ignored/Subscribe: {s0.message!r}")
        if "[resource: subscription token]" not in s0.render():
            fails.append(f"subscribe finding missing kind tag: {s0.render()!r}")

    # --- POOL001 ArrayPool: a buffer rented but never returned leaks; a returned
    #     one stays silent; tag [resource: pooled buffer].
    with open(_POOL_FIXTURE, encoding="utf-8") as f:
        pfacts = json.load(f)
    pfindings = check_facts(pfacts)
    checks += 1
    if len(pfindings) != 1 or pfindings[0].event != "leaky":
        fails.append(f"expected 1 pool finding (leaky), got "
                     f"{[(x.event, x.code) for x in pfindings]}")
    else:
        p0 = pfindings[0]
        checks += 1
        if (p0.file, p0.line, p0.code) != ("PooledBufferSample.cs", 9, "OWN001"):
            fails.append(f"wrong pool location/code: {p0.file}:{p0.line} {p0.code}")
        if "rented" not in p0.message or "returned" not in p0.message:
            fails.append(f"pool message missing rented/returned: {p0.message!r}")
        if "[resource: pooled buffer]" not in p0.render():
            fails.append(f"pool finding missing kind tag: {p0.render()!r}")

    # --- P-005 D1 local IDisposable: a `new`'d local never disposed leaks; an
    #     explicitly disposed one stays silent; tag [resource: disposable].
    with open(_LOCAL_FIXTURE, encoding="utf-8") as f:
        lfacts = json.load(f)
    lfindings = check_facts(lfacts)
    checks += 1
    if len(lfindings) != 1 or lfindings[0].event != "leaky":
        fails.append(f"expected 1 local-disposable finding (leaky), got "
                     f"{[(x.event, x.code) for x in lfindings]}")
    else:
        l0 = lfindings[0]
        checks += 1
        if (l0.file, l0.line, l0.code) != ("LocalDisposableSample.cs", 12, "OWN001"):
            fails.append(f"wrong local location/code: {l0.file}:{l0.line} {l0.code}")
        if "local IDisposable" not in l0.message or "MemoryStream" not in l0.message:
            fails.append(f"local message missing text/type: {l0.message!r}")
        if "[resource: disposable]" not in l0.render():
            fails.append(f"local finding missing kind tag: {l0.render()!r}")

    # --- P-016 B0b/B2 escape-via-projection (the GTM UnitOfWork case): a local
    #     IDisposable created and captured ONLY through member access into a returned
    #     DEFERRED query is still a leak — the bare handle never escapes, so the flow
    #     detector keeps it tracked and it is disposed on no path -> OWN001 on the
    #     local. Distilled from CatalogService.GetProductsFromCatalogWODocuments; pins
    #     that the projection capture does NOT mask the leak (a naive `using` cannot
    #     fix it, so the find must survive). `uow` is released on no path, so the
    #     OWN001 reads "is never disposed" (not the partial-path wording). Tag
    #     [resource: disposable].
    with open(_UOW_FLOW_FIXTURE, encoding="utf-8") as f:
        wfacts = json.load(f)
    wfindings = check_facts(wfacts)
    checks += 1
    if len(wfindings) != 1 or wfindings[0].code != "OWN001":
        fails.append(f"expected 1 flow OWN001 (UnitOfWork 'uow'), got "
                     f"{[(x.event, x.code) for x in wfindings]}")
    else:
        w0 = wfindings[0]
        checks += 1
        if (w0.file, w0.line, w0.code) != ("UnitOfWorkFlowSample.cs", 26, "OWN001"):
            fails.append(f"wrong uow location/code: {w0.file}:{w0.line} {w0.code}")
        if w0.event != "uow" or \
                w0.component != "CatalogService.GetProductsFromCatalogWODocuments":
            fails.append(f"wrong uow local/component: {w0.event!r}/{w0.component!r}")
        if "is never disposed" not in w0.message or "uow" not in w0.message:
            fails.append(f"uow message wrong (want 'is never disposed'): {w0.message!r}")
        # a 0-release leak must NOT borrow the partial-path wording.
        if "every path" in w0.message:
            fails.append(f"uow (0 releases) wrongly used the partial-path wording: "
                         f"{w0.message!r}")
        if "[resource: disposable]" not in w0.render():
            fails.append(f"uow finding missing kind tag: {w0.render()!r}")

    # --- the other OWN001 wording: a local released on SOME branch but leaked on
    #     another (the LeakOnElse shape) reads "may not be disposed on every path",
    #     NOT "never disposed" — the everReleased split (extractor flow body has a
    #     release of this local somewhere) chooses between the two phrasings.
    with open(_LEAK_ON_ELSE_FIXTURE, encoding="utf-8") as f:
        efacts = json.load(f)
    efindings = check_facts(efacts)
    checks += 1
    if len(efindings) != 1 or efindings[0].code != "OWN001":
        fails.append(f"expected 1 flow OWN001 (LeakOnElse 'leak'), got "
                     f"{[(x.event, x.code) for x in efindings]}")
    else:
        e0 = efindings[0]
        checks += 1
        if (e0.file, e0.line) != ("FlowLocalsSample.cs", 23):
            fails.append(f"wrong leak-on-else location: {e0.file}:{e0.line}")
        if "may not be disposed on every path" not in e0.message:
            fails.append(f"leak-on-else message wrong (want partial-path): "
                         f"{e0.message!r}")
        if "is never disposed" in e0.message:
            fails.append(f"partial-release leak wrongly used the never-disposed "
                         f"wording: {e0.message!r}")

    # --- one leak, one finding: the exception-edge try-lowering injects an
    #     exceptional exit (a bare `return` while the local is live) before each
    #     may-throw statement. A local never disposed then leaks on BOTH that exit and
    #     the normal fall-through, so the core emits OWN001 twice for the same local.
    #     Every flow-local diagnostic remaps to the acquire line, so the two collapse
    #     to byte-identical findings — the bridge must keep exactly one (TryNeverDisposed
    #     'tfLeak'). Without the dedup this returns 2.
    with open(_TWO_EXITS_FIXTURE, encoding="utf-8") as f:
        tefacts = json.load(f)
    tefindings = check_facts(tefacts)
    checks += 1
    if [(x.event, x.code, x.line) for x in tefindings] != [("tfLeak", "OWN001", 105)]:
        fails.append(f"expected exactly one OWN001 on 'tfLeak'@105 (two leaking exits "
                     f"deduped), got {[(x.event, x.code, x.line) for x in tefindings]}")

    # --- exception-edge RECALL slice: the edge now recurses into nested compound statements,
    #     treats a constructor (`new`) as a throw point, and fires under a TYPED catch. The
    #     core must flag the nested throw-before-dispose ('nestedLeak') and the prior resource
    #     a throwing constructor skips ('ctorPrior'), while the dispose-before-throw nested
    #     case ('cif', disposed in every branch before the throw) and the not-yet-acquired
    #     later resource ('ctorLater', acquired after the edge) stay silent. Pins the verdict
    #     on the exact IR the new lowering emits (the C# lowering itself is covered in CI).
    with open(_NESTED_THROW_FIXTURE, encoding="utf-8") as f:
        ntfacts = json.load(f)
    ntfindings = check_facts(ntfacts)
    checks += 1
    got = sorted((x.event, x.code, x.line) for x in ntfindings)
    if got != [("ctorPrior", "OWN001", 217), ("nestedLeak", "OWN001", 201)]:
        fails.append(f"expected OWN001 on 'nestedLeak'@201 and 'ctorPrior'@217 only "
                     f"(nested clean 'cif' and later-acquired 'ctorLater' stay silent), "
                     f"got {got}")

    # --- finally-before-return + switch lowering: a `return` inside a try-with-finally runs
    #     the finally first (a finally-disposed resource is released on the return path ->
    #     silent), an early return that skips a later dispose leaks ('r2'), a no-default switch
    #     where every case disposes stays silent (last case is the tail — no phantom no-match
    #     leak, the Model-A soundness choice for exhaustive switches), and a switch whose
    #     else/default branch leaks is flagged ('s2'). Pins the verdicts on the IR the new
    #     lowering emits (the C# lowering itself is covered in CI).
    with open(_FINALLY_SWITCH_FIXTURE, encoding="utf-8") as f:
        fsfacts = json.load(f)
    fsfindings = check_facts(fsfacts)
    checks += 1
    fsgot = sorted((x.event, x.code, x.line) for x in fsfindings)
    if fsgot != [("r2", "OWN001", 20), ("s2", "OWN001", 40)]:
        fails.append(f"expected OWN001 on 'r2'@20 (early-return leak) and 's2'@40 (switch "
                     f"else-branch leak) only — clean 'r' (finally before return) and 's' "
                     f"(switch all-dispose) stay silent — got {fsgot}")

    # --- flow-path pool labelling: an ArrayPool Rent leaked on the flow path must read as a
    #     "pooled buffer" (Return wording + [resource: pooled buffer]), not the generic
    #     "disposable". The extractor stamps the acquire's kind 'pool'; the bridge words a
    #     partial-path leak ('may not be returned to the pool on every path'), a never-returned
    #     one ('rented but never returned'), and leaves a plain disposable on the same shape
    #     ('may not be disposed on every path'). Regression for the mislabel the --body-throw-
    #     edges Npgsql capstone surfaced (CompositeBuilder/BitStringConverters ArrayPool rents).
    with open(_POOL_PARTIAL_FIXTURE, encoding="utf-8") as f:
        ppfacts = json.load(f)
    ppfindings = check_facts(ppfacts)
    by = {x.event: x for x in ppfindings}
    checks += 1
    # exactly three findings, one per fixture function — no extra/duplicate findings
    # (a regression that adds a spurious pool/disposable finding must fail here, not slip
    # past the per-event checks below). CodeRabbit hardening.
    if set(by.keys()) != {"buf", "nbuf", "d"} or len(ppfindings) != 3:
        fails.append(f"pool-label: expected exactly ['buf','nbuf','d'], got "
                     f"{[x.event for x in ppfindings]}")
    want = [
        ("buf", "pooled buffer", "may not be returned to the pool on every path", "pooled buffer"),
        ("nbuf", "pooled buffer", "rented but never returned to the pool", "pooled buffer"),
        ("d", "disposable", "may not be disposed on every path", "disposable"),
    ]
    for ev, kind, msg_sub, tag in want:
        fdg = by.get(ev)
        if fdg is None or fdg.code != "OWN001":
            fails.append(f"pool-label: expected OWN001 on '{ev}', got {fdg!r}")
        elif fdg.kind != kind:
            fails.append(f"pool-label: '{ev}' kind want {kind!r}, got {fdg.kind!r}")
        elif msg_sub not in fdg.message:
            fails.append(f"pool-label: '{ev}' message want {msg_sub!r}, "
                         f"got {fdg.message!r}")
        elif f"[resource: {tag}]" not in fdg.render():
            fails.append(f"pool-label: '{ev}' render want [resource: {tag}], got {fdg.render()!r}")

    # --- P-016 A1 reaches the frontend: a `while` flow body (the extractor now
    #     lowers loops instead of skipping the method) routes through the core's
    #     worklist fixpoint. A resource acquired before the loop and released INSIDE
    #     it double-releases on the 2nd turn (OWN003) and leaks on the 0-trip path
    #     (OWN001) — both on the same local, proving the loop op reaches the fixpoint
    #     end-to-end through the bridge (not just on the `.own` DSL).
    with open(_WHILE_FIXTURE, encoding="utf-8") as f:
        wlfacts = json.load(f)
    wlfindings = check_facts(wlfacts)
    checks += 1
    codes = sorted({x.code for x in wlfindings})
    if len(wlfindings) != 2 or codes != ["OWN001", "OWN003"] \
            or any(x.event != "c" for x in wlfindings):
        fails.append(f"expected cross-iteration OWN001+OWN003 on 'c', got "
                     f"{[(x.event, x.code) for x in wlfindings]}")
    else:
        checks += 1
        if any(x.file != "FlowLocalsSample.cs" or x.line != 20 for x in wlfindings):
            fails.append(f"wrong while-xiter location: "
                         f"{[(x.file, x.line) for x in wlfindings]}")
        if not all(x.kind == "disposable" for x in wlfindings):
            fails.append("while-xiter findings missing [resource: disposable] kind")

    # --- DI001 captive dependency (P-006): a singleton capturing a scoped
    #     service (directly or through a transient) is flagged at its
    #     registration site; safe registrations stay silent.
    from ownlang.di import Service, find_captive_dependencies

    # unit: the graph check itself (singleton->scoped and singleton->transient->
    # scoped are captive; singleton->singleton->scoped and scoped->scoped are not).
    svcs = [
        Service("A", "singleton", ("B",)),            # A -> scoped B : captive
        Service("B", "scoped", ()),
        Service("C", "singleton", ("T",)),            # C -> transient -> scoped : captive
        Service("T", "transient", ("B",)),
        Service("D", "singleton", ("E",)),            # D -> singleton E : safe here
        Service("E", "singleton", ("B",)),            # E -> scoped B : E's own bug
        Service("F", "scoped", ("B",)),               # scoped -> scoped : safe
    ]
    captives = find_captive_dependencies(svcs)
    checks += 1
    captors = sorted((c.singleton, c.captured) for c in captives)
    if captors != [("A", "B"), ("C", "B"), ("E", "B")]:
        fails.append(f"captive-dependency set wrong: {captors}")
    checks += 1
    cpath = next((c.path for c in captives if c.singleton == "C"), None)
    if cpath != ("C", "T", "B"):
        fails.append(f"transitive captive path wrong: {cpath}")

    # --- DI003 (P-006): a transient IDisposable captured by a singleton is promoted
    #     to application lifetime (warning). The same DFS as DI001, target = transient
    #     AND disposable; a non-disposable transient and a scoped capture stay silent.
    from ownlang.di import find_captured_transient_disposables
    dsvcs = [
        Service("Cache", "singleton", ("Conn",),  # -> transient disposable: DI003
                ctor_file="Cache.cs", ctor_line=4, ctor_type="Cache"),
        Service("Conn", "transient", (), disposable=True),
        Service("Warm", "singleton", ("Mid",)),  # -> transient -> disposable
        Service("Mid", "transient", ("Pool",), disposable=False),
        Service("Pool", "transient", (), disposable=True),
        Service("Plain", "singleton", ("Plumb",)),  # transient, not disposable: silent
        Service("Plumb", "transient", (), disposable=False),
        Service("Cap", "singleton", ("Db",)),  # singleton -> scoped: DI001, not DI003
        Service("Db", "scoped", (), disposable=True),
    ]
    di3 = find_captured_transient_disposables(dsvcs)
    checks += 1
    got3 = sorted((c.singleton, c.captured) for c in di3)
    if got3 != [("Cache", "Conn"), ("Warm", "Pool")]:
        fails.append(f"DI003 set wrong: {got3}")
    checks += 1
    if any("IDisposable" not in c.message for c in di3):
        fails.append("DI003 message missing 'IDisposable'")
    checks += 1
    # DI003 carries the consuming-constructor anchor too, naming the IMPL that owns the ctor
    # (regression guard: the DI003 collector must pass consumed_type, like DI001/DI002).
    cache3 = next((c for c in di3 if c.singleton == "Cache"), None)
    c3want = "[consumed by the 'Cache' constructor at Cache.cs:4]"
    if cache3 is None or c3want not in cache3.message:
        fails.append(f"DI003 message missing consuming-constructor anchor: "
                     f"{cache3.message if cache3 else None!r}")
    # bridge: DI003 surfaces as a WARNING-severity finding; `disposable` is parsed.
    di3facts = {"ownir_version": 0, "module": "X", "components": [], "functions": [],
                "services": [
                    {"name": "Cache", "lifetime": "singleton", "deps": ["Conn"],
                     "file": "S.cs", "line": 7},
                    {"name": "Conn", "lifetime": "transient", "deps": [],
                     "disposable": True, "file": "S.cs", "line": 8},
                ]}
    di3b = [x for x in check_facts(di3facts) if x.code == "DI003"]
    checks += 1
    if len(di3b) != 1 or di3b[0].severity != "warning" or di3b[0].component != "Cache":
        fails.append(f"DI003 bridge finding wrong: "
                     f"{[(x.component, x.severity) for x in di3b]}")
    checks += 1
    # P-015 flow: captor singleton -> captured transient IDisposable, each at its registration
    # site, ending with the DI003 family label.
    if not di3b or di3b[0].flow != (
            ("S.cs", 7, "singleton 'Cache' (captor)"),
            ("S.cs", 8, "captures transient IDisposable 'Conn'")):
        fails.append(f"DI003 flow wrong: {di3b[0].flow if di3b else None!r}")

    # --- DI002 (P-006): a scoped service held by a singleton via WeakReference<T> is a
    #     weak captive (warning). The weak edge lives in `weak_deps`, OFF the DI001 strong
    #     graph; a weak ref to a singleton is no mismatch, so it stays silent.
    from ownlang.di import find_weak_captive_dependencies
    wsvcs = [
        Service("WeakCache", "singleton", deps=(), weak_deps=("Db",)),   # weak->scoped: DI002
        Service("Db", "scoped", ()),
        Service("Strong", "singleton", deps=("Db",)),                    # strong->scoped: DI001
        Service("WeakReport", "singleton", deps=(), weak_deps=("Uow",)),  # weak->transient->scoped
        Service("Uow", "transient", deps=("Db",)),
        Service("WeakClock", "singleton", deps=(), weak_deps=("Clk",)),  # weak -> singleton: safe
        Service("Clk", "singleton", ()),
    ]
    di2 = find_weak_captive_dependencies(wsvcs)
    checks += 1
    got2 = sorted((c.singleton, c.captured) for c in di2)
    if got2 != [("WeakCache", "Db"), ("WeakReport", "Db")]:
        fails.append(f"DI002 set wrong: {got2}")
    checks += 1
    # the transitive weak captive carries the full path through the weakly-held transient.
    wpath = next((c.path for c in di2 if c.singleton == "WeakReport"), None)
    if wpath != ("WeakReport", "Uow", "Db"):
        fails.append(f"DI002 transitive path wrong: {wpath}")
    checks += 1
    # the weak captive must NOT also be a strong DI001 (weak edge is off the strong graph).
    if any(c.singleton == "WeakCache" for c in find_captive_dependencies(wsvcs)):
        fails.append("DI002 weak captive wrongly also flagged as DI001")
    checks += 1
    if not di2 or "WeakReference" not in di2[0].message:
        fails.append("DI002 message missing 'WeakReference'")
    # bridge: DI002 surfaces as a WARNING; `weak_deps` is parsed and kept off DI001.
    di2facts = {"ownir_version": 0, "module": "X", "components": [], "functions": [],
                "services": [
                    {"name": "WeakCache", "lifetime": "singleton", "deps": [],
                     "weak_deps": ["Db"], "file": "S.cs", "line": 9},
                    {"name": "Db", "lifetime": "scoped", "deps": [], "file": "S.cs", "line": 10},
                ]}
    di2b = check_facts(di2facts)
    checks += 1
    di2only = [x for x in di2b if x.code == "DI002"]
    if (len(di2only) != 1 or di2only[0].severity != "warning"
            or di2only[0].component != "WeakCache"):
        fails.append("DI002 bridge finding wrong: "
                     f"{[(x.component, x.severity) for x in di2only]}")
    checks += 1
    if any(x.code == "DI001" for x in di2b):
        fails.append("DI002 bridge wrongly also produced a DI001")
    checks += 1
    # P-015 flow: ends with the DI002 family label "weakly captures scoped service".
    if not di2only or di2only[0].flow != (
            ("S.cs", 9, "singleton 'WeakCache' (captor)"),
            ("S.cs", 10, "weakly captures scoped service 'Db'")):
        fails.append(f"DI002 flow wrong: {di2only[0].flow if di2only else None!r}")

    # --- DI004 (P-006): a transient IDisposable resolved BY HAND from a singleton's injected
    #     root IServiceProvider (the service-locator anti-pattern, warning). Only singletons are
    #     considered; the resolved type's transient subtree is walked like DI003, so a disposable
    #     reached directly OR through a non-disposable transient wrapper is reported. A
    #     scope-resolved, scoped-class, or non-disposable+scoped-dep-only resolution stays silent.
    from ownlang.di import find_explicit_root_resolutions
    rsvcs = [
        Service("Resolver", "singleton", deps=(), root_resolves=("Conn",),
                root_resolve_sites=(("Conn", "R.cs", 42),)),  # direct: DI004, call site 42
        Service("Conn", "transient", (), disposable=True),
        Service("Wrap", "singleton", deps=(), root_resolves=("Mid",),
                root_resolve_sites=(("Mid", "R.cs", 88),)),  # transitive: DI004, entry call site 88
        Service("Mid", "transient", ("Pool",)),  # non-disposable wrapper -> disposable
        Service("Pool", "transient", (), disposable=True),
        Service("Plain", "singleton", deps=(), root_resolves=("Uow",)),  # silent: scoped dep only
        Service("Uow", "transient", ("Db",)),
        Service("Db", "scoped", ()),
        Service("Req", "scoped", deps=(), root_resolves=("Conn",)),  # silent: scoped class
        Service("Hold", "singleton", deps=(), root_resolves=("Clk",)),  # silent: ->singleton
        Service("Clk", "singleton", ()),
    ]
    di4 = find_explicit_root_resolutions(rsvcs)
    checks += 1
    got4 = sorted((c.singleton, c.resolved) for c in di4)
    if got4 != [("Resolver", "Conn"), ("Wrap", "Pool")]:
        fails.append(f"DI004 set wrong: {got4}")
    checks += 1
    # the transitive resolution carries the full path through the non-disposable wrapper.
    rpath = next((c.path for c in di4 if c.singleton == "Wrap"), None)
    if rpath != ("Wrap", "Mid", "Pool"):
        fails.append(f"DI004 transitive path wrong: {rpath}")
    checks += 1
    if not di4 or not all("service-locator" in c.message for c in di4):
        fails.append("DI004 message missing 'service-locator'")
    checks += 1
    # DI004 records the GetRequiredService CALL SITE: the direct case its own site (42), and the
    # transitive case the ENTRY type's site (Mid@88), NOT the dragged-in disposable's.
    direct4 = next((c for c in di4 if c.singleton == "Resolver"), None)
    trans4 = next((c for c in di4 if c.singleton == "Wrap"), None)
    d4loc = (direct4.resolved_file, direct4.resolved_line) if direct4 else None
    if direct4 is None or d4loc != ("R.cs", 42):
        fails.append(f"DI004 direct call-site (resolved_*) wrong: {d4loc!r}")
    checks += 1
    t4loc = (trans4.resolved_file, trans4.resolved_line) if trans4 else None
    if trans4 is None or t4loc != ("R.cs", 88):
        fails.append(f"DI004 transitive call-site (resolved_*) wrong: {t4loc!r}")
    # bridge: DI004 surfaces as a WARNING, anchored at the CALL SITE (R.cs:42) — its real
    # consumer (Codex) — with the REGISTRATION (S.cs:5) as the Finding.related secondary and
    # named in the message tail. (registration site S.cs:5 differs from the call site R.cs:42.)
    di4facts = {"ownir_version": 0, "module": "X", "components": [], "functions": [],
                "services": [
                    {"name": "Resolver", "lifetime": "singleton", "deps": [],
                     "root_resolves": ["Conn"], "file": "S.cs", "line": 5,
                     "root_resolve_sites": [{"type": "Conn", "file": "R.cs", "line": 42}]},
                    {"name": "Conn", "lifetime": "transient", "deps": [],
                     "disposable": True, "file": "S.cs", "line": 6},
                ]}
    di4b = check_facts(di4facts)
    checks += 1
    di4only = [x for x in di4b if x.code == "DI004"]
    if (len(di4only) != 1 or di4only[0].severity != "warning"
            or (di4only[0].file, di4only[0].line) != ("R.cs", 42)
            or di4only[0].related != (("S.cs", 5, "registration of singleton 'Resolver'"),)
            or "[singleton registered at S.cs:5]" not in di4only[0].message):
        fails.append("DI004 bridge finding wrong: "
                     f"{[(x.file, x.line, x.related) for x in di4only]}")
    checks += 1
    # the explicit root resolution is a CALL SITE, not a registration-graph edge: it must not
    # also produce a DI001/DI002/DI003 (the singleton has no scoped/transient ctor dependency).
    if any(x.code in ("DI001", "DI002", "DI003") for x in di4b):
        fails.append("DI004 wrongly also produced a graph DI00x finding")
    checks += 1
    # P-015 flow: DI004 anchors at the CALL site (R.cs:42), but the reachability slice begins at
    # the REGISTRATION site (S.cs:5) and ends with "leaks transient IDisposable" — the flow's
    # first hop deliberately differs from the finding's own (call-site) location.
    if not di4only or di4only[0].flow != (
            ("S.cs", 5, "singleton 'Resolver' (captor)"),
            ("S.cs", 6, "leaks transient IDisposable 'Conn'")):
        fails.append(f"DI004 flow wrong: {di4only[0].flow if di4only else None!r}")
    checks += 1
    if di4only and di4only[0].flow[0][:2] == (di4only[0].file, di4only[0].line):
        fails.append("DI004 flow must start at the registration site, not the call-site anchor")

    # --- DI005 (P-006): a singleton that resolves a SCOPED service from a scope it CREATES
    #     (IServiceScopeFactory.CreateScope()) and CACHES it into a field — the scope-per-op
    #     fix done wrong (warning). Only singletons; the cached value must REACH a scoped service
    #     — a cached scoped type directly, or a cached transient that ctor-injects one (the DFS
    #     follows transients like DI001). A cached singleton, or a transient with NO scoped strong
    #     path, is not this violation; a scope-resolved value USED in the scope and not cached
    #     produces no `scope_cached` entry, so it stays silent.
    from ownlang.di import find_scope_cached_captives
    csvcs = [
        # caches scoped -> DI005, store site 21:
        Service("Cacher", "singleton", deps=(), scope_cached=("Db",),
                scope_cache_sites=(("Db", "C.cs", 21),)),
        Service("Db", "scoped", ()),
        # caches a TRANSIENT that ctor-injects scoped Db -> transitive DI005, store site 30:
        Service("TransCacher", "singleton", deps=(), scope_cached=("Uow",),
                scope_cache_sites=(("Uow", "C.cs", 30),)),
        Service("Uow", "transient", deps=("Db",)),
        Service("CacheTmp", "singleton", deps=(), scope_cached=("Tmp",)),  # silent: no scoped dep
        Service("Tmp", "transient", (), disposable=True),
        Service("CacheClk", "singleton", deps=(), scope_cached=("Clk",)),  # silent: singleton
        Service("Clk", "singleton", ()),
        Service("ReqCacher", "scoped", deps=(), scope_cached=("Db",)),     # silent: not singleton
        Service("GoodScope", "singleton", deps=(), scope_cached=()),       # silent: not cached
    ]
    di5 = find_scope_cached_captives(csvcs)
    checks += 1
    got5 = sorted((c.singleton, c.captured) for c in di5)
    if got5 != [("Cacher", "Db"), ("TransCacher", "Db")]:
        fails.append(f"DI005 set wrong: {got5}")
    checks += 1
    # the transitive cache carries the full path through the cached transient.
    tpath = next((c.path for c in di5 if c.singleton == "TransCacher"), None)
    if tpath != ("TransCacher", "Uow", "Db"):
        fails.append(f"DI005 transitive path wrong: {tpath}")
    checks += 1
    direct5 = next((c for c in di5 if c.singleton == "Cacher"), None)
    if direct5 is None or "use-after-dispose" not in direct5.message:
        fails.append("DI005 message missing 'use-after-dispose'")
    checks += 1
    # DI005 records the field-STORE site of the cached ENTRY (Cacher@C.cs:21) for anchoring —
    # and the transitive case anchors at the ENTRY (Uow) store, not the dragged-in Db.
    if direct5 is None or (direct5.cached_file, direct5.cached_line) != ("C.cs", 21):
        fails.append(f"DI005 cache-site wrong: "
                     f"{(direct5.cached_file, direct5.cached_line) if direct5 else None}")
    checks += 1
    trans5 = next((c for c in di5 if c.singleton == "TransCacher"), None)
    if trans5 is None or (trans5.cached_file, trans5.cached_line) != ("C.cs", 30):
        fails.append(f"DI005 transitive cache-site wrong: "
                     f"{(trans5.cached_file, trans5.cached_line) if trans5 else None}")
    # bridge: DI005 surfaces as a WARNING anchored at the STORE site (C.cs:21), with the
    # REGISTRATION (S.cs:7) as the related secondary and named in the message tail.
    di5facts = {"ownir_version": 0, "module": "X", "components": [], "functions": [],
                "services": [
                    {"name": "Cacher", "lifetime": "singleton", "deps": [],
                     "scope_cached": ["Db"], "file": "S.cs", "line": 7,
                     "scope_cache_sites": [{"type": "Db", "file": "C.cs", "line": 21}]},
                    {"name": "Db", "lifetime": "scoped", "deps": [], "file": "S.cs", "line": 8},
                ]}
    di5b = check_facts(di5facts)
    checks += 1
    di5only = [x for x in di5b if x.code == "DI005"]
    if (len(di5only) != 1 or di5only[0].severity != "warning"
            or (di5only[0].file, di5only[0].line) != ("C.cs", 21)
            or di5only[0].related != (("S.cs", 7, "registration of singleton 'Cacher'"),)
            or "[singleton registered at S.cs:7]" not in di5only[0].message):
        fails.append("DI005 bridge finding wrong: "
                     f"{[(x.file, x.line, x.related) for x in di5only]}")
    checks += 1
    # DI005 is a store-site property, not a registration-graph edge: the singleton has no scoped
    # ctor dependency, so it must not also produce a DI001/DI002/DI003/DI004.
    if any(x.code in ("DI001", "DI002", "DI003", "DI004") for x in di5b):
        fails.append("DI005 wrongly also produced another DI00x finding")
    checks += 1
    # P-015 flow: DI005 anchors at the field-STORE site (C.cs:21), but the slice begins at the
    # REGISTRATION site (S.cs:7) and ends with "caches scoped service".
    if not di5only or di5only[0].flow != (
            ("S.cs", 7, "singleton 'Cacher' (captor)"),
            ("S.cs", 8, "caches scoped service 'Db'")):
        fails.append(f"DI005 flow wrong: {di5only[0].flow if di5only else None!r}")
    checks += 1
    if di5only and di5only[0].flow[0][:2] == (di5only[0].file, di5only[0].line):
        fails.append("DI005 flow must start at the registration site, not the store-site anchor")

    # bridge: the fixture surfaces exactly the two captive singletons as DI001
    # at their registration lines; the clock/scoped-to-scoped stay silent.
    with open(_DI_FIXTURE, encoding="utf-8") as f:
        difacts = json.load(f)
    difindings = check_facts(difacts)
    checks += 1
    di = sorted((x.component, x.line, x.code) for x in difindings
                if x.code == "DI001")
    if di != [("EmailSender", 12, "DI001"), ("ReportService", 15, "DI001")]:
        fails.append(f"DI001 findings wrong: {di}")
    checks += 1
    if any(x.component == "Clock" for x in difindings):
        fails.append("a dependency-free singleton was wrongly flagged")
    checks += 1
    em = next((x for x in difindings if x.component == "EmailSender"), None)
    if em is None or "captures scoped service 'AppDbContext'" not in em.message:
        fails.append(f"DI001 message missing captive text: "
                     f"{em.message if em else None!r}")
    checks += 1
    # P-006 Q#1: the finding anchors at the REGISTRATION site (line 12) but names the
    # CONSUMING CONSTRUCTOR too — here a DIFFERENT file (EmailSender.cs:5), both in the
    # message tail and as a structured related location (-> SARIF relatedLocations).
    consumed = "[consumed by the 'EmailSender' constructor at EmailSender.cs:5]"
    if em is None or consumed not in em.message:
        fails.append(f"DI001 message missing consuming-constructor anchor: "
                     f"{em.message if em else None!r}")
    checks += 1
    if em is None or em.related != (("EmailSender.cs", 5,
                                     "consuming constructor of 'EmailSender'"),):
        fails.append(f"DI001 related (consuming ctor) location wrong: "
                     f"{em.related if em else None!r}")
    checks += 1
    # the related location rides into SARIF as a relatedLocations entry (clickable in
    # GitHub code scanning), distinct from the primary registration-site location.
    em_sarif = next((r for r in build_sarif(difindings)["runs"][0]["results"]
                     if r["properties"].get("component") == "EmailSender"), None)
    rel = (em_sarif or {}).get("relatedLocations")
    if (not rel or rel[0]["physicalLocation"]["artifactLocation"]["uri"] != "EmailSender.cs"
            or rel[0]["physicalLocation"]["region"]["startLine"] != 5):
        fails.append(f"DI001 SARIF relatedLocations wrong: {rel!r}")
    checks += 1
    # P-015: the captive's retention path also rides along as an ORDERED reachability slice
    # (SARIF codeFlows) — the "why is this held, and through what?" trace relatedLocations
    # cannot express. The direct captive is a 2-hop path: captor singleton -> captured scoped,
    # each anchored at its registration site.
    if em is None or em.flow != (
            ("Startup.cs", 12, "singleton 'EmailSender' (captor)"),
            ("Startup.cs", 13, "captures scoped service 'AppDbContext'")):
        fails.append(f"DI001 EmailSender reachability flow wrong: {em.flow if em else None!r}")
    checks += 1
    em_flows = (em_sarif or {}).get("codeFlows")
    em_locs = em_flows[0]["threadFlows"][0]["locations"] if em_flows else []
    if (len(em_locs) != 2
            or em_locs[0]["location"]["physicalLocation"]["region"]["startLine"] != 12
            or em_locs[-1]["location"]["physicalLocation"]["region"]["startLine"] != 13):
        fails.append(f"DI001 SARIF codeFlows wrong: {em_flows!r}")
    checks += 1
    # the TRANSITIVE captive (ReportService -> UnitOfWork(transient) -> AppDbContext(scoped))
    # renders a 3-hop slice, with the transient a labelled pass-through middle step.
    rs = next((x for x in difindings
               if x.component == "ReportService" and x.code == "DI001"), None)
    if rs is None or rs.flow != (
            ("Startup.cs", 15, "singleton 'ReportService' (captor)"),
            ("Startup.cs", 16, "via 'UnitOfWork'"),
            ("Startup.cs", 13, "captures scoped service 'AppDbContext'")):
        fails.append(f"DI001 ReportService transitive flow wrong: {rs.flow if rs else None!r}")
    checks += 1
    # a DI001 whose ctor location is UNKNOWN degrades cleanly — no suffix, no related.
    nolocf = check_facts({"ownir_version": 0, "module": "X", "components": [], "functions": [],
                          "services": [
                              {"name": "Cap", "lifetime": "singleton", "deps": ["Sc"],
                               "file": "S.cs", "line": 3},
                              {"name": "Sc", "lifetime": "scoped", "deps": [],
                               "file": "S.cs", "line": 4}]})
    cap = next((x for x in nolocf if x.code == "DI001"), None)
    if cap is None or "consumed by the" in cap.message or cap.related != ():
        fails.append(f"DI001 without ctor loc should omit the consuming-ctor anchor: "
                     f"{(cap.message, cap.related) if cap else None!r}")
    checks += 1
    # an INTERFACE registration (AddSingleton<IBilling, Billing>): the singleton is 'IBilling'
    # (no ctor) but the consuming ctor is 'Billing's, so the finding must name the IMPL Billing,
    # never the interface (Codex). ctor_type carries the impl through the fact.
    ifacef = check_facts({"ownir_version": 0, "module": "X", "components": [], "functions": [],
                          "services": [
                              {"name": "IBilling", "lifetime": "singleton", "deps": ["Db"],
                               "file": "Startup.cs", "line": 8, "ctor_file": "Billing.cs",
                               "ctor_line": 11, "ctor_type": "Billing"},
                              {"name": "Db", "lifetime": "scoped", "deps": [],
                               "file": "Startup.cs", "line": 9}]})
    ib = next((x for x in ifacef if x.code == "DI001"), None)
    if ib is None or "[consumed by the 'Billing' constructor at Billing.cs:11]" not in ib.message:
        fails.append(f"DI001 interface-registration must name the IMPL ctor (Billing), not "
                     f"the interface: {ib.message if ib else None!r}")
    checks += 1
    if ib is None or "'IBilling' constructor" in ib.message \
            or ib.related != (("Billing.cs", 11, "consuming constructor of 'Billing'"),):
        fails.append(f"DI001 interface-registration named the interface ctor or wrong related: "
                     f"{(ib.message, ib.related) if ib else None!r}")
    checks += 1
    # an unknown lifetime must fail loudly at load (external input).
    if not _load_raises({"ownir_version": OWNIR_VERSION, "components": [],
                         "services": [{"name": "X", "lifetime": "perpetual"}]}):
        fails.append("an invalid service lifetime did not raise OwnIRError")
    checks += 1
    if not _load_raises({"ownir_version": OWNIR_VERSION, "components": [],
                         "services": [{"lifetime": "singleton"}]}):
        fails.append("a missing/empty service name did not raise OwnIRError")
    checks += 1
    if not _load_raises({"ownir_version": OWNIR_VERSION, "components": [],
                         "services": [{"name": "X", "lifetime": "singleton",
                                       "line": "NaN"}]}):
        fails.append("a non-integer service line did not raise OwnIRError")
    checks += 1
    # weak_deps (DI002) is validated like deps: a non-array (here a string, which would
    # otherwise be char-split by tuple()) must fail loudly at load, not silently (Codex).
    if not _load_raises({"ownir_version": OWNIR_VERSION, "components": [],
                         "services": [{"name": "X", "lifetime": "singleton",
                                       "weak_deps": "abc"}]}):
        fails.append("a non-array service weak_deps did not raise OwnIRError")
    checks += 1
    # root_resolves (DI004) is validated the same way — a non-array must raise at load.
    if not _load_raises({"ownir_version": OWNIR_VERSION, "components": [],
                         "services": [{"name": "X", "lifetime": "singleton",
                                       "root_resolves": "abc"}]}):
        fails.append("a non-array service root_resolves did not raise OwnIRError")
    checks += 1
    # ctor_line (the consuming-constructor anchor, P-006 Q#1) is validated like line.
    if not _load_raises({"ownir_version": OWNIR_VERSION, "components": [],
                         "services": [{"name": "X", "lifetime": "singleton",
                                       "ctor_line": "NaN"}]}):
        fails.append("a non-integer service ctor_line did not raise OwnIRError")
    checks += 1
    # ctor_type (the impl owning the ctor) is validated as a string.
    if not _load_raises({"ownir_version": OWNIR_VERSION, "components": [],
                         "services": [{"name": "X", "lifetime": "singleton",
                                       "ctor_type": 5}]}):
        fails.append("a non-string service ctor_type did not raise OwnIRError")
    checks += 1
    # root_resolve_sites (DI004 call-site metadata) must be an array of {type,file,line} objects.
    if not _load_raises({"ownir_version": OWNIR_VERSION, "components": [],
                         "services": [{"name": "X", "lifetime": "singleton",
                                       "root_resolve_sites": [{"type": "T", "line": "NaN"}]}]}):
        fails.append("a malformed service root_resolve_sites did not raise OwnIRError")
    checks += 1
    # scope_cached (DI005) is validated like root_resolves — a non-array must raise at load.
    if not _load_raises({"ownir_version": OWNIR_VERSION, "components": [],
                         "services": [{"name": "X", "lifetime": "singleton",
                                       "scope_cached": "abc"}]}):
        fails.append("a non-array service scope_cached did not raise OwnIRError")
    checks += 1
    # scope_cache_sites (DI005 store-site metadata) must be an array of {type,file,line} objects.
    if not _load_raises({"ownir_version": OWNIR_VERSION, "components": [],
                         "services": [{"name": "X", "lifetime": "singleton",
                                       "scope_cache_sites": [{"type": "Db", "line": "NaN"}]}]}):
        fails.append("a malformed service scope_cache_sites did not raise OwnIRError")

    # --- P-014 Tier A: an "unresolved-subscription" marker (the extractor could
    #     not bind the `+=` LHS to an event) is NOT a leak — the lowering skips it
    #     (no phantom OWN001) and it surfaces as an advisory OWN050 note; a real
    #     subscription in the same component still leaks (OWN001, non-advisory).
    with open(_UNRESOLVED_FIXTURE, encoding="utf-8") as f:
        ufacts = json.load(f)
    usrc, _ = to_own(ufacts)
    checks += 1
    try:
        parse(usrc)
    except Exception as e:
        fails.append(f"lowered unresolved facts do not parse: {e}")
    # the marker must NOT be lowered to an acquire (else it becomes a phantom leak)
    checks += 1
    if usrc.count("acquire Subscription") != 1:
        fails.append(f"unresolved marker was lowered to an acquire: {usrc!r}")
    ufindings = check_facts(ufacts)
    unotes = [x for x in ufindings if x.code == "OWN050"]
    uleaks = [x for x in ufindings if x.code == "OWN001"]
    checks += 1
    if len(unotes) != 1 or not unotes[0].advisory:
        fails.append(f"expected 1 advisory OWN050 note, got "
                     f"{[(x.code, x.advisory) for x in ufindings]}")
    else:
        u0 = unotes[0]
        checks += 1
        if (u0.file, u0.line) != ("GridViewModel.cs", 20):
            fails.append(f"wrong OWN050 location: {u0.file}:{u0.line}")
        if "leakage analysis skipped" not in u0.message:
            fails.append(f"OWN050 message wrong: {u0.message!r}")
        if "[resource: unresolved reference]" not in u0.render():
            fails.append(f"OWN050 missing kind tag: {u0.render()!r}")
    checks += 1
    if len(uleaks) != 1 or uleaks[0].advisory:
        fails.append(f"expected 1 real OWN001 leak (non-advisory), got "
                     f"{[(x.code, x.advisory) for x in ufindings]}")

    # --- P-004 region escape (OWN014): a `capture` (a TOKENLESS strong
    #     subscription) whose event SOURCE provably outlives the subscriber routes
    #     through the lifetime/region engine and lands as OWN014 at the C# site —
    #     proving C# subscription facts reach the region core (docs/lifetimes.md
    #     slice #3), not only the hand-written `.own` DSL. An injected-source
    #     capture (unknown lifetime) stays SILENT: the region model is conservative
    #     where it cannot prove the source outlives — precise where the token model
    #     (resource:"subscription") only warns. The lowered sketch still parses.
    with open(_CAPTURE_FIXTURE, encoding="utf-8") as f:
        cfacts = json.load(f)
    csrc, _ = to_own(cfacts)
    checks += 1
    try:
        parse(csrc)
    except Exception as e:
        fails.append(f"lowered capture facts do not parse: {e}")
    # a capture must NOT be lowered to an acquire STATEMENT (`= acquire`, the token
    # model -> OWN001); it lowers to `subscribe self to ...` under a lifetime
    # region. (The resource PRELUDE legitimately contains the word "acquire" as a
    # member keyword, so match the `= acquire` statement form, not bare "acquire".)
    checks += 1
    if "= acquire" in csrc or "subscribe self to cap_0" not in csrc \
            or "lifetime Subscriber < Process" not in csrc:
        fails.append(f"capture lowered to the wrong shape (want subscribe+lifetime, "
                     f"no acquire statement): {csrc!r}")
    cfindings = check_facts(cfacts)
    checks += 1
    if [(x.component, x.line, x.code) for x in cfindings] != \
            [("ThemeViewModel", 18, "OWN014")]:
        fails.append(f"expected one OWN014 region escape (ThemeViewModel@18), got "
                     f"{[(x.component, x.line, x.code) for x in cfindings]}")
    else:
        c0 = cfindings[0]
        checks += 1
        if c0.severity is not None:
            fails.append(f"region escape should be error-tier (None), got "
                         f"{c0.severity!r}")
        if "region escape" not in c0.message or \
                "UserPreferenceChanged" not in c0.message:
            fails.append(f"region-escape message wrong: {c0.message!r}")
        if "[resource: subscription token]" not in c0.render():
            fails.append(f"region-escape finding missing kind tag: {c0.render()!r}")
    # the injected-source capture (unknown lifetime) must NOT be reported.
    checks += 1
    if any(x.component == "OrdersViewModel" for x in cfindings):
        fails.append("injected-source capture (unprovable) was wrongly reported")
    # a RELEASED static capture (a matching `-=` on close — the fix shape) is
    # mitigated and must stay silent: the region lowering skips a released capture,
    # mirroring a released token subscription. This is what keeps the extractor's
    # static-source reroute from flagging correctly-unsubscribed code.
    checks += 1
    if any(x.component == "CleanThemeViewModel" for x in cfindings):
        fails.append("a released (unsubscribed) static capture was wrongly reported")

    # issue #199: a static-source capture whose handler is an inline LAMBDA gets the
    # same OWN014 region escape, now carrying the "inline lambda — no '-=' handle" note
    # (the extractor stamps lambda:true). A NON-capturing static lambda is dropped
    # upstream by the extractor's non-retaining gate, so a lambda reaching this branch
    # is a capturing one; a method-group capture (lambda absent, above) has no note.
    checks += 1
    lamcap = check_facts({"module": "M", "components": [
        {"name": "PingVM", "file": "PingVM.cs", "subscriptions": [
            {"event": "SomeBus.Pinged", "handler": "(_, _) => _n++", "line": 7,
             "released": False, "resource": "capture", "source": "static",
             "lambda": True}]}]})
    if [(x.component, x.line, x.code) for x in lamcap] != [("PingVM", 7, "OWN014")]:
        fails.append(f"a lambda static capture should raise OWN014 (PingVM@7), got "
                     f"{[(x.component, x.line, x.code) for x in lamcap]}")
    elif "inline lambda" not in lamcap[0].message or "-=" not in lamcap[0].message:
        fails.append(f"OWN014 lambda-capture message missing the no-'-=' note: "
                     f"{lamcap[0].message!r}")

    # --- P-006 + P-004: DI-sourced region escape. An injected subscription whose
    #     source TYPE resolves (via the `services` graph) to a longer-lived DI
    #     registration than the subscriber is a PROVABLE region escape -> OWN014,
    #     not the honest OWN001 warning the unresolved case gets. A singleton source
    #     captured by an un-registered UI VM escapes; a transient source is proven
    #     SAFE by the SAME registration order and stays silent (the precision win).
    #     This unifies the DI-lifetime model (di.py) with the region engine —
    #     lifetimes the intra-procedural model cannot know locally now come from the
    #     registration graph. The lowered sketch still parses.
    with open(_DI_CAPTURE_FIXTURE, encoding="utf-8") as f:
        dcfacts = json.load(f)
    dcsrc, _ = to_own(dcfacts)
    checks += 1
    try:
        parse(dcsrc)
    except Exception as e:
        fails.append(f"lowered di-capture facts do not parse: {e}")
    dcfindings = check_facts(dcfacts)
    checks += 1
    if [(x.component, x.line, x.code) for x in dcfindings] != \
            [("CustomerViewModel", 14, "OWN014")]:
        fails.append(f"expected one DI region escape (CustomerViewModel@14 OWN014), "
                     f"got {[(x.component, x.line, x.code) for x in dcfindings]}")
    else:
        d0 = dcfindings[0]
        checks += 1
        if d0.severity is not None:
            fails.append(f"DI region escape should be error-tier (None), got "
                         f"{d0.severity!r}")
        if "singleton" not in d0.message or "IEventBus" not in d0.message:
            fails.append(f"DI-escape message missing singleton/type: {d0.message!r}")
        if "captive" not in d0.message:
            fails.append(f"DI-escape message should name the captive escape: "
                         f"{d0.message!r}")
        if "[resource: subscription token]" not in d0.render():
            fails.append(f"DI-escape finding missing kind tag: {d0.render()!r}")
    # the transient-sourced subscription is PROVEN SAFE by the same DI order (a
    # transient source cannot outlive the subscriber) -> silent, not a warning.
    checks += 1
    if any(x.component == "ProbeViewModel" for x in dcfindings):
        fails.append("a transient-sourced injected subscription (proven safe) "
                     "was wrongly reported")
    # regression: the SAME injected subscription with NO source_type / no services
    # keeps the honest OWN001 WARNING (the unresolved-lifetime hedge) — additive,
    # nothing escalates without the DI graph.
    checks += 1
    warn = check_facts({"module": "M", "components": [
        {"name": "Vm", "file": "Vm.cs", "subscriptions": [
            {"event": "bus.X", "handler": "h", "line": 5, "released": False,
             "resource": "subscription", "source": "injected"}]}]})
    if [(x.code, x.severity) for x in warn] != [("OWN001", "warning")]:
        fails.append(f"injected sub without DI info should stay an OWN001 warning, "
                     f"got {[(x.code, x.severity) for x in warn]}")
    # P-015: a DI-sourced subscription escape (OWN014) carries a CROSS-FILE slice — the
    # subscribe site -> where the longer-lived source service was registered (its lifetime
    # is *why* the subscriber escapes). The source hop comes from the services graph.
    checks += 1
    esc = check_facts({"ownir_version": 0, "module": "M", "functions": [],
        "components": [{"name": "Vm", "file": "VM.cs", "subscriptions": [
            {"event": "bus.Tick", "handler": "OnTick", "line": 11, "released": False,
             "resource": "subscription", "source": "injected", "source_type": "IBus"}]}],
        "services": [
            {"name": "IBus", "lifetime": "singleton", "deps": [],
             "file": "Startup.cs", "line": 7},
            {"name": "Vm", "lifetime": "transient", "deps": ["IBus"],
             "file": "Startup.cs", "line": 8}]})
    e14 = next((x for x in esc if x.code == "OWN014"), None)
    if e14 is None or e14.flow != (
            ("VM.cs", 11, "'Vm' subscribes 'bus.Tick' to 'IBus' here"),
            ("Startup.cs", 7, "source 'IBus' (singleton) registered here — outlives 'Vm'")):
        fails.append(f"DI-source OWN014 escape flow wrong: {e14.flow if e14 else None!r}")

    # --- P-006/2b: COMPOSITIONAL ownership transfer through the bridge. A C#
    #     method's ownership contract (a `consume`/`borrow` parameter) lowers to a
    #     core signature; a `call` op lowers to the core's Call, whose effects
    #     `lower_call` resolves from that signature. So cross-method handoff is
    #     checked compositionally by the SAME analyze() — no new checker, and no
    #     whole-program analysis (the signature is the cut). `archive(consume s)`
    #     takes ownership; `run` uses `s` after handing it off (OWN002); `leak`
    #     never discharges (OWN001); `run_ok` hands off correctly and is NOT a
    #     false leak though it never releases (the obligation moved to archive).
    with open(_HANDOFF_FIXTURE, encoding="utf-8") as f:
        hfacts = json.load(f)
    hfindings = check_facts(hfacts)
    checks += 1
    got = sorted((x.component, x.line, x.code) for x in hfindings)
    if got != [("leak", 18, "OWN001"), ("run", 24, "OWN002")]:
        fails.append(f"expected compositional handoff verdicts "
                     f"[leak@18 OWN001, run@24 OWN002], got {got}")
    # the correct consumer (archive) and the correct handoff (run_ok) must be
    # SILENT — the contract discharges the caller's obligation, no false leak.
    checks += 1
    if any(x.component in ("archive", "run_ok") for x in hfindings):
        fails.append("a correct consume contract / handoff was wrongly reported "
                     "(false positive on the compositional path)")
    # the use-after-handoff is OWN002 (use after the resource was consumed by the
    # callee), the same code .own produces for use-after-consume.
    checks += 1
    run_f = [x for x in hfindings if x.component == "run"]
    if not (run_f and "after it is disposed" in run_f[0].message
            and "[resource: disposable]" in run_f[0].render()):
        fails.append(f"use-after-handoff should read as use-after-disposal, got "
                     f"{[x.render() for x in run_f]}")
    checks += 1
    # P-015: the flow-local finding carries a reachability slice — where the resource was
    # acquired -> where it is used after its obligation moved (the precise violation line the
    # primary anchor, at the acquire, does not itself show).
    if not run_f or run_f[0].flow != (
            ("Archiver.cs", 24, "acquired 's' here"),
            ("Archiver.cs", 26, "used here after it was released/returned")):
        fails.append(f"flow-local OWN002 reachability flow wrong: "
                     f"{run_f[0].flow if run_f else None!r}")

    # regression (codex review): an undischarged `consume` parameter must MAP to a
    # finding AT the parameter, not crash check_facts. Before params carried an
    # origin, the core's OWN001 on the owned param had subject=None and the bridge
    # raised "cannot map back" instead of reporting the leak.
    checks += 1
    pf = check_facts({"module": "M", "functions": [
        {"name": "bad", "file": "X.cs",
         "params": [{"name": "s", "effect": "consume", "line": 5}],
         "body": [{"op": "use", "var": "s", "line": 6}]}]})
    if [(x.component, x.line, x.code) for x in pf] != [("bad", 5, "OWN001")]:
        fails.append(f"undischarged consume param should map to OWN001@5, got "
                     f"{[(x.component, x.line, x.code) for x in pf]}")

    # regression (CodeRabbit review): the DI region-escape reroute is scoped to
    # subscriptions. A non-subscription resource (here a timer) with an incidental
    # injected source/source_type must keep its OWN resource path, not be rerouted
    # into the DI escape (OWN014).
    checks += 1
    tf = check_facts({"module": "M",
        "components": [{"name": "Vm", "file": "Vm.cs", "subscriptions": [
            {"event": "t.Elapsed", "handler": "h", "line": 7, "released": False,
             "resource": "timer", "source": "injected", "source_type": "IBus"}]}],
        "services": [{"name": "IBus", "lifetime": "singleton", "deps": [],
                      "file": "S.cs", "line": 1}]})
    if [(x.code, x.kind) for x in tf] != [("OWN001", "timer")]:
        fails.append(f"timer with incidental injected source should stay a timer "
                     f"leak (OWN001/timer), not reroute to OWN014: "
                     f"{[(x.code, x.kind) for x in tf]}")

    # --- P-006/2b v1: CONTRACT INFERENCE. A callee's ownership contract is derived
    #     from its OWN body when no `effect` is annotated -- the bounded inter-
    #     procedural step that lets first-party C# be checked without annotating
    #     every method. `archive` releases its param -> inferred CONSUME (caller
    #     `run` then trips use-after-handoff OWN002); `peek` only reads its param ->
    #     inferred BORROW (caller `keep` keeps ownership and leaks OWN001 when it
    #     forgets to release; `ok` is clean when it releases). NO effect appears in
    #     the fixture -- every contract here is inferred.
    with open(_INFER_FIXTURE, encoding="utf-8") as f:
        ifacts = json.load(f)
    ifindings = check_facts(ifacts)
    checks += 1
    got = sorted((x.component, x.line, x.code) for x in ifindings)
    if got != [("keep", 31, "OWN001"), ("run", 24, "OWN002")]:
        fails.append(f"contract inference verdicts wrong: expected [keep@31 OWN001 "
                     f"(borrow inferred -> caller owns), run@24 OWN002 (consume "
                     f"inferred -> use after handoff)], got {got}")
    checks += 1
    if any(x.component in ("archive", "peek", "ok") for x in ifindings):
        fails.append("contract inference produced a false positive on a correct "
                     "callee/handoff (archive/peek/ok must be silent)")
    # an EXPLICIT effect always wins over inference: `consume` declared on a param
    # whose body only USES it (which would INFER borrow) keeps the owned obligation,
    # so the undischarged param leaks OWN001 rather than being silently borrowed.
    checks += 1
    ov = check_facts({"module": "M", "functions": [
        {"name": "g", "file": "G.cs",
         "params": [{"name": "s", "effect": "consume", "line": 1}],
         "body": [{"op": "use", "var": "s", "line": 2}]}]})
    if [(x.component, x.code) for x in ov] != [("g", "OWN001")]:
        fails.append(f"explicit `consume` should win over inferred borrow (owned "
                     f"param leaks OWN001), got {[(x.component, x.code) for x in ov]}")
    # regression (codex review): inference does NOT treat `return` as a consume
    # signal, and a value-bearing `return` no longer crashes the bridge. A function
    # that returns an owned local/param gets an owned return type, so the value
    # ESCAPES (is discharged) -- no false leak, no unmapped OWN035 crash.
    checks += 1
    rf = check_facts({"module": "M", "functions": [
        {"name": "make", "file": "R.cs",
         "body": [{"op": "acquire", "var": "s", "line": 1},
                  {"op": "return", "var": "s", "line": 2}]},
        {"name": "passthrough", "file": "R.cs", "params": [{"name": "s", "line": 5}],
         "body": [{"op": "return", "var": "s", "line": 6}]}]})
    if rf:
        fails.append(f"a value-bearing return should be a clean escape (no crash, no "
                     f"false leak), got {[(x.component, x.code) for x in rf]}")
    # --- P-005 D5.1: TRANSITIVE ownership transfer. A param ONLY forwarded to
    #     another call used to stay plain (the v1 give-up); the interprocedural
    #     summary solver (ownlang/ownership.py) now resolves it through the callee's
    #     contract. `forward(s)` hands s to `sink(consume)`, so forward's own param
    #     is inferred CONSUME — the give-up that `_infer_param_effect` left plain.
    _FWD = [
        {"name": "forward", "file": "F.cs", "params": [{"name": "s", "line": 1}],
         "body": [{"op": "call", "callee": "sink", "args": ["s"], "line": 2}]},
        {"name": "sink", "file": "F.cs",
         "params": [{"name": "x", "effect": "consume", "line": 5}],
         "body": [{"op": "release", "var": "x", "line": 6}]},
    ]
    # a caller that releases s AFTER forwarding double-discharges it: the obligation
    # already moved to `sink` through `forward`, so the later release is OWN002.
    checks += 1
    d51 = check_facts({"module": "M", "functions": [*_FWD,
        {"name": "caller", "file": "F.cs",
         "body": [{"op": "acquire", "var": "s", "line": 10},
                  {"op": "call", "callee": "forward", "args": ["s"], "line": 11},
                  {"op": "release", "var": "s", "line": 12}]}]})
    got51 = [(x.component, x.line, x.code) for x in d51]
    if got51 != [("caller", 10, "OWN002")]:
        fails.append("D5.1 transitive consume: release after handoff must be "
                     f"OWN002@10 (anchored at acquire), got {got51}")
    # the correct handoff (forward and let go) is SILENT — and this is a precision
    # WIN: before D5.1 forward's param was plain, so the caller's acquired-but-never-
    # released s read as a false OWN001 leak; now the obligation provably moved.
    checks += 1
    ok51 = check_facts({"module": "M", "functions": [*_FWD,
        {"name": "caller_ok", "file": "F.cs",
         "body": [{"op": "acquire", "var": "s", "line": 20},
                  {"op": "call", "callee": "forward", "args": ["s"], "line": 21}]}]})
    if ok51:
        fails.append("a correctly forwarded handoff must be silent (obligation moved "
                     f"to sink), got {[(x.component, x.code) for x in ok51]}")
    # two hops: outer -> mid -> sink(consume). The chain resolves within the depth
    # cap, so a caller using s after forwarding to `outer` is use-after-handoff.
    checks += 1
    twohop = check_facts({"module": "M", "functions": [
        {"name": "outer", "file": "F.cs", "params": [{"name": "s", "line": 1}],
         "body": [{"op": "call", "callee": "mid", "args": ["s"], "line": 2}]},
        {"name": "mid", "file": "F.cs", "params": [{"name": "s", "line": 5}],
         "body": [{"op": "call", "callee": "sink2", "args": ["s"], "line": 6}]},
        {"name": "sink2", "file": "F.cs",
         "params": [{"name": "x", "effect": "consume", "line": 9}],
         "body": [{"op": "release", "var": "x", "line": 10}]},
        {"name": "user", "file": "F.cs",
         "body": [{"op": "acquire", "var": "s", "line": 15},
                  {"op": "call", "callee": "outer", "args": ["s"], "line": 16},
                  {"op": "use", "var": "s", "line": 17}]}]})
    got2h = [(x.component, x.line, x.code) for x in twohop]
    if got2h != [("user", 15, "OWN002")]:
        fails.append("D5.1 two-hop transitive consume should be "
                     f"OWN002@user:15 (anchored at acquire), got {got2h}")
    # a param forwarded to a BORROW-only callee resolves to borrow (not consume):
    # the caller keeps ownership, so forwarding then RELEASING is clean — proving we
    # never over-consume a forwarded borrow (which would false-positive the release).
    checks += 1
    bok = check_facts({"module": "M", "functions": [
        {"name": "peek_fwd", "file": "F.cs", "params": [{"name": "s", "line": 1}],
         "body": [{"op": "call", "callee": "peek2", "args": ["s"], "line": 2}]},
        {"name": "peek2", "file": "F.cs", "params": [{"name": "x", "line": 5}],
         "body": [{"op": "use", "var": "x", "line": 6}]},
        {"name": "keep_ok", "file": "F.cs",
         "body": [{"op": "acquire", "var": "s", "line": 10},
                  {"op": "call", "callee": "peek_fwd", "args": ["s"], "line": 11},
                  {"op": "release", "var": "s", "line": 12}]}]})
    if bok:
        fails.append("forwarding to a borrow-only callee then releasing must be clean "
                     f"(no over-consume), got {[(x.component, x.code) for x in bok]}")
    # (Codex P2) an EXPLICIT effect seeds the skeleton even with no body evidence: a
    # contract-only `sink_c(x consume)` resolves `must`, so the forwarder `fwd_c` is
    # consume and a caller using s after the handoff is OWN002. (sink_c itself leaks
    # OWN001 — an undischarged consume obligation — which is the expected existing
    # behaviour, included here so the assertion is exact.)
    checks += 1
    expl = check_facts({"module": "M", "functions": [
        {"name": "fwd_c", "file": "F.cs", "params": [{"name": "s", "line": 1}],
         "body": [{"op": "call", "callee": "sink_c", "args": ["s"], "line": 2}]},
        {"name": "sink_c", "file": "F.cs",
         "params": [{"name": "x", "effect": "consume", "line": 5}], "body": []},
        {"name": "use_c", "file": "F.cs",
         "body": [{"op": "acquire", "var": "s", "line": 10},
                  {"op": "call", "callee": "fwd_c", "args": ["s"], "line": 11},
                  {"op": "use", "var": "s", "line": 12}]}]})
    gotx = sorted((x.component, x.code) for x in expl)
    if gotx != [("sink_c", "OWN001"), ("use_c", "OWN002")]:
        fails.append(f"D5.1 explicit-effect seed should resolve through a "
                     f"forwarder (use_c OWN002), got {gotx}")
    # (Codex P2 / CodeRabbit) a CONDITIONAL forward must resolve to `may`, not `must`:
    # `maybe(s){ if(c) sink(s); }` consumes s on only one path, so a caller that uses s
    # after `maybe(s)` must stay SILENT (no false OWN002 on the non-forward path).
    checks += 1
    cond = check_facts({"module": "M", "functions": [
        {"name": "maybe", "file": "F.cs", "params": [{"name": "s", "line": 1}],
         "body": [{"op": "if", "then": [
             {"op": "call", "callee": "sink", "args": ["s"], "line": 3}], "else": [],
             "line": 2}]},
        {"name": "sink", "file": "F.cs",
         "params": [{"name": "x", "effect": "consume", "line": 6}],
         "body": [{"op": "release", "var": "x", "line": 7}]},
        {"name": "user_c", "file": "F.cs",
         "body": [{"op": "acquire", "var": "s", "line": 10},
                  {"op": "call", "callee": "maybe", "args": ["s"], "line": 11},
                  {"op": "release", "var": "s", "line": 12}]}]})
    gotc = [(x.component, x.code, x.advisory) for x in cond]
    if gotc != [("user_c", "OWN051", True)]:
        fails.append("D5.1 conditional forward must be `may`: no verdicts, one "
                     f"honest OWN051 advisory (d5 §5), got {gotc}")
    # (TZ D1) a CONDITIONAL release joins to `may`, not a flattened `consume`:
    # `cond_rel(x){ if(c) release x; }` keeps x on the other path, so a caller that
    # disposes defensively after the call stays SILENT. Before the fix the inferred
    # consume charged that caller a false OWN002 and the helper a false OWN001 —
    # the null-guard-dispose-helper idiom read as two findings.
    checks += 1
    d1c = check_facts({"module": "M", "functions": [
        {"name": "cond_rel", "file": "D.cs", "params": [{"name": "x", "line": 1}],
         "body": [{"op": "if", "line": 2,
                   "then": [{"op": "release", "var": "x", "line": 3}], "else": []}]},
        {"name": "careful", "file": "D.cs",
         "body": [{"op": "acquire", "var": "r", "line": 10},
                  {"op": "call", "callee": "cond_rel", "args": ["r"], "line": 11},
                  {"op": "release", "var": "r", "line": 12}]}]})
    gotd1c = [(x.component, x.code, x.advisory) for x in d1c]
    if gotd1c != [("careful", "OWN051", True)]:
        fails.append("TZ D1: a partial release must join to `may` — no verdicts, "
                     f"one OWN051 advisory, got {gotd1c}")
    # (TZ D1) release in BOTH branches IS all-paths: consume survives, and the
    # careless caller keeps its true OWN002 — the refinement costs no recall here.
    checks += 1
    d1b = check_facts({"module": "M", "functions": [
        {"name": "both_rel", "file": "D.cs", "params": [{"name": "x", "line": 1}],
         "body": [{"op": "if", "line": 2,
                   "then": [{"op": "release", "var": "x", "line": 3}],
                   "else": [{"op": "release", "var": "x", "line": 4}]}]},
        {"name": "reuse_b", "file": "D.cs",
         "body": [{"op": "acquire", "var": "r", "line": 10},
                  {"op": "call", "callee": "both_rel", "args": ["r"], "line": 11},
                  {"op": "release", "var": "r", "line": 12}]}]})
    gotd1b = [(x.component, x.line, x.code) for x in d1b]
    if gotd1b != [("reuse_b", 10, "OWN002")]:
        fails.append("TZ D1: an all-paths (both-branch) release is still consume, "
                     f"got {gotd1b}")
    # (TZ D1) a release inside a `while` body is never definite (zero-trip): plain.
    checks += 1
    d1w = check_facts({"module": "M", "functions": [
        {"name": "loop_rel", "file": "D.cs", "params": [{"name": "x", "line": 1}],
         "body": [{"op": "while", "line": 2,
                   "body": [{"op": "release", "var": "x", "line": 3}]}]},
        {"name": "loop_user", "file": "D.cs",
         "body": [{"op": "acquire", "var": "r", "line": 10},
                  {"op": "call", "callee": "loop_rel", "args": ["r"], "line": 11},
                  {"op": "release", "var": "r", "line": 12}]}]})
    gotd1w = [(x.component, x.code, x.advisory) for x in d1w]
    if gotd1w != [("loop_user", "OWN051", True)]:
        fails.append("TZ D1: a while-body release is zero-trip-partial — no "
                     f"verdicts, one OWN051 advisory, got {gotd1w}")
    # (TZ D1) an early `return` on an unreleased path blocks the definite claim:
    # `guard(x){ if(c) return; release x; }` does not release on the guard path.
    checks += 1
    d1g = check_facts({"module": "M", "functions": [
        {"name": "guard_rel", "file": "D.cs", "params": [{"name": "x", "line": 1}],
         "body": [{"op": "if", "line": 2, "then": [{"op": "return", "line": 3}],
                   "else": []},
                  {"op": "release", "var": "x", "line": 4}]},
        {"name": "guard_user", "file": "D.cs",
         "body": [{"op": "acquire", "var": "r", "line": 10},
                  {"op": "call", "callee": "guard_rel", "args": ["r"], "line": 11},
                  {"op": "release", "var": "r", "line": 12}]}]})
    gotd1g = [(x.component, x.code, x.advisory) for x in d1g]
    if gotd1g != [("guard_user", "OWN051", True)]:
        fails.append("TZ D1: an early-return-unreleased path blocks consume — no "
                     f"verdicts, one OWN051 advisory, got {gotd1g}")
    # (TZ D1) release-then-return in a branch plus a fall-through release IS
    # all-paths — the walk credits a released early exit, so consume survives.
    checks += 1
    d1rr = check_facts({"module": "M", "functions": [
        {"name": "rel_ret", "file": "D.cs", "params": [{"name": "x", "line": 1}],
         "body": [{"op": "if", "line": 2,
                   "then": [{"op": "release", "var": "x", "line": 3},
                            {"op": "return", "line": 4}],
                   "else": []},
                  {"op": "release", "var": "x", "line": 5}]},
        {"name": "rel_ret_user", "file": "D.cs",
         "body": [{"op": "acquire", "var": "r", "line": 10},
                  {"op": "call", "callee": "rel_ret", "args": ["r"], "line": 11},
                  {"op": "use", "var": "r", "line": 12}]}]})
    gotrr = [(x.component, x.line, x.code) for x in d1rr]
    if gotrr != [("rel_ret_user", 10, "OWN002")]:
        fails.append("TZ D1: release-then-return + fall-through release is all-paths "
                     f"consume, got {gotrr}")
    # (TZ D1) a wrapper forwarding to a partial releaser inherits `may` through the
    # solver — the transitive claim degrades to plain (silence) too.
    checks += 1
    d1f = check_facts({"module": "M", "functions": [
        {"name": "cond_rel2", "file": "D.cs", "params": [{"name": "x", "line": 1}],
         "body": [{"op": "if", "line": 2,
                   "then": [{"op": "release", "var": "x", "line": 3}], "else": []}]},
        {"name": "via", "file": "D.cs", "params": [{"name": "s", "line": 6}],
         "body": [{"op": "call", "callee": "cond_rel2", "args": ["s"], "line": 7}]},
        {"name": "via_user", "file": "D.cs",
         "body": [{"op": "acquire", "var": "r", "line": 10},
                  {"op": "call", "callee": "via", "args": ["r"], "line": 11},
                  {"op": "release", "var": "r", "line": 12}]}]})
    gotd1f = [(x.component, x.code, x.advisory) for x in d1f]
    if gotd1f != [("via_user", "OWN051", True)]:
        fails.append("TZ D1: forwarding to a partial releaser degrades to `may` "
                     f"transitively — no verdicts, one OWN051 advisory, got {gotd1f}")
    # (итерация 6) the optimistic default made REAL: an owned local DROPPED after
    # a may-call must be silent (untracked), not an OWN001 — before this fix a
    # plain arg left the obligation with the caller, so the ubiquitous null-guard
    # helper usage `var r = new X(); Cleanup(r);` (no dispose after — Cleanup IS
    # the disposer) fabricated a leak. The gap is the OWN051 advisory instead.
    checks += 1
    d6drop = check_facts({"module": "M", "functions": [
        {"name": "cond_rel3", "file": "U.cs", "params": [{"name": "x", "line": 1}],
         "body": [{"op": "if", "line": 2,
                   "then": [{"op": "release", "var": "x", "line": 3}], "else": []}]},
        {"name": "drop_user", "file": "U.cs",
         "body": [{"op": "acquire", "var": "r", "line": 10},
                  {"op": "call", "callee": "cond_rel3", "args": ["r"], "line": 11}]}]})
    gotd6 = [(x.component, x.line, x.code, x.advisory) for x in d6drop]
    if gotd6 != [("drop_user", 11, "OWN051", True)]:
        fails.append("untrack: dropping a local after a may-call must be silent "
                     f"(one OWN051 advisory, no OWN001), got {gotd6}")
    # ... while a VERIFIED borrow keeps the obligation with the caller: dropping
    # after a borrow-only callee is the T3 recall win (a real OWN001, no OWN051) —
    # the untrack must never widen to verified contracts.
    checks += 1
    d6borrow = check_facts({"module": "M", "functions": [
        {"name": "peek3", "file": "U.cs", "params": [{"name": "x", "line": 1}],
         "body": [{"op": "use", "var": "x", "line": 2}]},
        {"name": "drop_b", "file": "U.cs",
         "body": [{"op": "acquire", "var": "r", "line": 10},
                  {"op": "call", "callee": "peek3", "args": ["r"], "line": 11}]}]})
    gotd6b = [(x.component, x.line, x.code, x.advisory) for x in d6borrow]
    if gotd6b != [("drop_b", 10, "OWN001", False)]:
        fails.append("untrack: a verified borrow must keep the caller's obligation "
                     f"(true OWN001 on drop, no advisory), got {gotd6b}")
    # a plain (never-acquired) value at a may-position is not a gap worth a note:
    # the OWN051 owned-local gate keeps the advisory channel quiet.
    checks += 1
    d6plain = check_facts({"module": "M", "functions": [
        {"name": "cond_rel4", "file": "U.cs", "params": [{"name": "x", "line": 1}],
         "body": [{"op": "if", "line": 2,
                   "then": [{"op": "release", "var": "x", "line": 3}], "else": []}]},
        {"name": "plain_user", "file": "U.cs",
         "body": [{"op": "call", "callee": "cond_rel4", "args": ["v"], "line": 11}]}]})
    if d6plain:
        fails.append("untrack: a non-owned value at a may-position must stay quiet, "
                     f"got {[(x.component, x.code) for x in d6plain]}")
    # (Codex P1) the untrack must not swallow PRE-call verdicts: a local is
    # tracked normally up to its top-level may-call, so a use-after-release
    # BEFORE the handoff still surfaces (before the fix the whole-body untrack
    # skipped the acquire and the real OWN002 vanished, leaving only OWN051).
    checks += 1
    p1pre = check_facts({"module": "M", "functions": [
        {"name": "cond_rel5", "file": "K.cs", "params": [{"name": "x", "line": 1}],
         "body": [{"op": "if", "line": 2,
                   "then": [{"op": "release", "var": "x", "line": 3}], "else": []}]},
        {"name": "pre_bug", "file": "K.cs",
         "body": [{"op": "acquire", "var": "r", "line": 10},
                  {"op": "release", "var": "r", "line": 11},
                  {"op": "use", "var": "r", "line": 12},
                  {"op": "call", "callee": "cond_rel5", "args": ["r"], "line": 13}]}]})
    gotp1 = sorted((x.component, x.code, x.advisory) for x in p1pre)
    if gotp1 != [("pre_bug", "OWN002", False), ("pre_bug", "OWN051", True)]:
        fails.append("kill-site untrack: a pre-call use-after-release must keep its "
                     f"OWN002 beside the OWN051 advisory, got {gotp1}")
    # (Codex P1) ... while the POST-call region keeps the optimistic silence: the
    # kill-site `$consume` discharges the obligation on every path through the
    # top-level call, so a defensive dispose after it is still uncharged.
    checks += 1
    p1post = check_facts({"module": "M", "functions": [
        {"name": "cond_rel6", "file": "K.cs", "params": [{"name": "x", "line": 1}],
         "body": [{"op": "if", "line": 2,
                   "then": [{"op": "release", "var": "x", "line": 3}], "else": []}]},
        {"name": "post_guard", "file": "K.cs",
         "body": [{"op": "acquire", "var": "r", "line": 10},
                  {"op": "call", "callee": "cond_rel6", "args": ["r"], "line": 11},
                  {"op": "release", "var": "r", "line": 12},
                  {"op": "use", "var": "r", "line": 13}]}]})
    gotp1p = [(x.component, x.code, x.advisory) for x in p1post]
    if gotp1p != [("post_guard", "OWN051", True)]:
        fails.append("kill-site untrack: post-call defensive dispose/use must stay "
                     f"silent (one OWN051 advisory), got {gotp1p}")
    # (Codex P2) an early return SKIPPING the single top-level forward makes the
    # handoff conditional: `guarded(x){ if(c) return; sink(x); }` must join to
    # `may`, so the guarded helper does not leak its own param and a caller's
    # defensive dispose is not charged a false OWN002 (the forward twin of D1).
    checks += 1
    p2er = check_facts({"module": "M", "functions": [
        {"name": "sink_er", "file": "K.cs",
         "params": [{"name": "x", "effect": "consume", "line": 1}],
         "body": [{"op": "release", "var": "x", "line": 2}]},
        {"name": "guarded", "file": "K.cs", "params": [{"name": "s", "line": 5}],
         "body": [{"op": "if", "line": 6, "then": [{"op": "return", "line": 7}],
                   "else": []},
                  {"op": "call", "callee": "sink_er", "args": ["s"], "line": 8}]},
        {"name": "guarded_user", "file": "K.cs",
         "body": [{"op": "acquire", "var": "r", "line": 10},
                  {"op": "call", "callee": "guarded", "args": ["r"], "line": 11},
                  {"op": "release", "var": "r", "line": 12}]}]})
    gotp2 = [(x.component, x.code, x.advisory) for x in p2er]
    if gotp2 != [("guarded_user", "OWN051", True)]:
        fails.append("S2 early return: a return-skipped forward must join to `may` "
                     f"— no verdicts, one OWN051 advisory, got {gotp2}")
    # (TZ D5) a failed MOS solve must degrade OBSERVABLY: the bridge drops to
    # no-MOS (checker stays alive, forwards stay plain — no fabricated verdicts)
    # and surfaces ONE advisory OWN052 naming the inner error. Before the fix the
    # whole interprocedural layer went dark silently. Patch the solver to raise —
    # no real facts input can make it throw today, which is exactly why the silent
    # `except` was never noticed.
    checks += 1
    import ownlang.ownir as _oi
    _mos_facts = {"module": "Dark", "functions": [
        {"name": "sink3", "file": "S.cs",
         "params": [{"name": "x", "line": 1}],
         "body": [{"op": "release", "var": "x", "line": 2}]},
        {"name": "hand", "file": "S.cs",
         "body": [{"op": "acquire", "var": "s", "line": 10},
                  {"op": "call", "callee": "sink3", "args": ["s"], "line": 11},
                  {"op": "release", "var": "s", "line": 12}]}]}
    _real_solve = _oi.solve
    def _boom(_sk):  # type: ignore[no-untyped-def]
        raise RuntimeError("synthetic solver failure")
    _oi.solve = _boom  # type: ignore[assignment]
    try:
        dark = check_facts(_mos_facts)
    finally:
        _oi.solve = _real_solve
    gotdark = [(x.code, x.component, x.advisory) for x in dark]
    if gotdark != [("OWN052", "Dark", True)] or \
            "synthetic solver failure" not in dark[0].message:
        fails.append("TZ D5: a failed solve must yield exactly one advisory OWN052 "
                     f"(and no fabricated verdicts), got {gotdark}")
    # ... and the SAME facts with a healthy solver carry no OWN052 — the consume
    # resolves interprocedurally again and the careless caller's OWN002 is back.
    checks += 1
    lit = check_facts(_mos_facts)
    gotlit = [(x.component, x.line, x.code) for x in lit]
    if gotlit != [("hand", 10, "OWN002")]:
        fails.append("TZ D5: healthy solve must carry no OWN052 and keep the true "
                     f"OWN002, got {gotlit}")
    # --- roadmap stage 1: the `summaries` dump (dump_summaries / `python -m
    #     ownlang summaries`). One deterministic document: solved MOS per method
    #     (sorted by key), the extern-boundary log (sorted), a `degraded` reason.
    #     This is the parity surface the Rust port of the inference layer will be
    #     diffed against, so its byte-stability IS the contract.
    from ownlang.ownir import dump_summaries
    _dump_facts = {"module": "M", "functions": [
        {"name": "B.Fwd", "file": "b.cs", "params": [{"name": "s", "line": 1}],
         "body": [{"op": "call", "callee": "Extern.Gone", "args": ["s"], "line": 2}]},
        {"name": "A.Make", "file": "a.cs",
         "body": [{"op": "acquire", "var": "r", "line": 1},
                  {"op": "return", "var": "r", "line": 2}]},
        {"name": "C.Sink", "file": "c.cs", "params": [{"name": "x", "line": 1}],
         "body": [{"op": "release", "var": "x", "line": 2}]}]}
    checks += 1
    doc = dump_summaries(_dump_facts)
    keys = [s["method"] for s in doc["summaries"]]
    kinds = {s["method"]: s["returns"]["owned"] for s in doc["summaries"]}
    transfers = {s["method"]: [p["transfer"] for p in s["params"]]
                 for s in doc["summaries"]}
    files = {s["method"]: s["file"] for s in doc["summaries"]}
    if (keys != ["A.Make", "B.Fwd", "C.Sink"]  # sorted by method key
            or kinds["A.Make"] != "fresh" or transfers["C.Sink"] != ["must"]
            or transfers["B.Fwd"] != ["unknown"]
            or doc["unresolved"] != ["Extern.Gone#0 (extern, no summary)"]
            or files["A.Make"] != "a.cs" or doc["degraded"] is not None):
        fails.append(f"summaries dump content wrong: {doc}")
    # byte-determinism: permuting `functions[]` input order must not change one byte
    # of the canonical dump — this is what makes it a parity artifact, not a debug log.
    checks += 1
    blob1 = json.dumps(doc, indent=2, sort_keys=True)
    _dump_facts["functions"].reverse()
    blob2 = json.dumps(dump_summaries(_dump_facts), indent=2, sort_keys=True)
    if blob1 != blob2:
        fails.append("summaries dump must be byte-identical under functions[] "
                     "input permutation")
    # a failed solve degrades the dump exactly like the checking path: empty
    # summaries + the reason in `degraded` — never a crash, never a half-document.
    checks += 1
    _real_swl = _oi.solve_with_log
    def _boom2(_sk):  # type: ignore[no-untyped-def]
        raise RuntimeError("synthetic dump failure")
    _oi.solve_with_log = _boom2  # type: ignore[assignment]
    try:
        darkdoc = dump_summaries(_dump_facts)
    finally:
        _oi.solve_with_log = _real_swl
    if (darkdoc["summaries"] != [] or darkdoc["unresolved"] != []
            or "synthetic dump failure" not in (darkdoc["degraded"] or "")):
        fails.append(f"degraded summaries dump wrong: {darkdoc}")
    # spec/Inference.md conformance: the advisory codes the spec names (OWN051,
    # OWN052) must be registered in the catalogue — a spec that references an
    # unregistered code, or a dropped code, is drift the build must catch.
    checks += 1
    missing = [c for c in ("OWN051", "OWN052") if c not in TITLES]
    if missing:
        fails.append(f"Inference.md names unregistered code(s): {missing}")
    # (§10 q2) same-name OVERLOADS are merged, not dropped: when EVERY overload of a
    # name consumes the forwarded arg, a forward to that name resolves to `must`, so a
    # caller using the local after the handoff is OWN002. Before the merge the name was
    # dropped → the forward stayed unknown → this leak was silently missed.
    checks += 1
    ovc = check_facts({"module": "M", "functions": [
        {"name": "C.M", "file": "F.cs", "params": [{"name": "a", "line": 1}],
         "body": [{"op": "release", "var": "a", "line": 2}]},
        {"name": "C.M", "file": "F.cs", "params": [{"name": "b", "line": 5}],
         "body": [{"op": "release", "var": "b", "line": 6}]},
        {"name": "ov_fwd", "file": "F.cs", "params": [{"name": "s", "line": 10}],
         "body": [{"op": "call", "callee": "C.M", "args": ["s"], "line": 11}]},
        {"name": "ov_use", "file": "F.cs",
         "body": [{"op": "acquire", "var": "s", "line": 20},
                  {"op": "call", "callee": "ov_fwd", "args": ["s"], "line": 21},
                  {"op": "use", "var": "s", "line": 22}]}]})
    gotov = sorted((x.component, x.code) for x in ovc)
    if gotov != [("ov_use", "OWN002")]:
        fails.append("§10 q2 agreeing overloads should resolve the forward to consume "
                     f"(ov_use OWN002), got {gotov}")
    # (§10 q2) when overloads DISAGREE (one consumes, one only borrows) the merge joins
    # to `may`, so the forward stays plain and a caller that releases the local itself is
    # clean — the conservative join never fabricates a `must` from an ambiguous name.
    checks += 1
    ovd = check_facts({"module": "M", "functions": [
        {"name": "C.N", "file": "F.cs", "params": [{"name": "a", "line": 1}],
         "body": [{"op": "release", "var": "a", "line": 2}]},
        {"name": "C.N", "file": "F.cs", "params": [{"name": "b", "line": 5}],
         "body": [{"op": "use", "var": "b", "line": 6}]},
        {"name": "ovn_fwd", "file": "F.cs", "params": [{"name": "s", "line": 10}],
         "body": [{"op": "call", "callee": "C.N", "args": ["s"], "line": 11}]},
        {"name": "ovn_use", "file": "F.cs",
         "body": [{"op": "acquire", "var": "s", "line": 20},
                  {"op": "call", "callee": "ovn_fwd", "args": ["s"], "line": 21},
                  {"op": "release", "var": "s", "line": 22}]}]})
    gotn = [(x.component, x.code, x.advisory) for x in ovd]
    if gotn != [("ovn_use", "OWN051", True)]:
        fails.append("§10 q2 disagreeing overloads must join to `may` — no "
                     f"verdicts, one OWN051 advisory, got {gotn}")
    # (Codex P2) a DIRECT call to disagreeing overloads must NOT mis-apply the last same-name
    # signature: the merged contract is `may`, so `acquire s; C.N(s); release s` stays silent.
    # (Before the fix the core's last-wins signature consumed s → a false OWN002.)
    checks += 1
    ovdir = check_facts({"module": "M", "functions": [
        {"name": "C.N", "file": "F.cs", "params": [{"name": "b", "line": 1}],
         "body": [{"op": "use", "var": "b", "line": 2}]},          # borrow
        {"name": "C.N", "file": "F.cs", "params": [{"name": "a", "line": 5}],
         "body": [{"op": "release", "var": "a", "line": 6}]},      # consume (defined last)
        {"name": "dN", "file": "F.cs",
         "body": [{"op": "acquire", "var": "s", "line": 10},
                  {"op": "call", "callee": "C.N", "args": ["s"], "line": 11},
                  {"op": "release", "var": "s", "line": 12}]}]})
    gotdir = [(x.component, x.code, x.advisory) for x in ovdir]
    if gotdir != [("dN", "OWN051", True)]:
        fails.append("§10 q2 direct call to disagreeing overloads carries no "
                     f"verdicts, one OWN051 advisory (merged may), got {gotdir}")
    # the same DIRECT path DOES apply consume when every overload agrees: both consume, so
    # `acquire s; C.M(s); use s` is use-after-consume OWN002 (the channel carries the merged
    # `must`, not a dropped effect).
    checks += 1
    ovdir2 = check_facts({"module": "M", "functions": [
        {"name": "C.M", "file": "F.cs", "params": [{"name": "a", "line": 1}],
         "body": [{"op": "release", "var": "a", "line": 2}]},
        {"name": "C.M", "file": "F.cs", "params": [{"name": "b", "line": 5}],
         "body": [{"op": "release", "var": "b", "line": 6}]},
        {"name": "dM", "file": "F.cs",
         "body": [{"op": "acquire", "var": "s", "line": 10},
                  {"op": "call", "callee": "C.M", "args": ["s"], "line": 11},
                  {"op": "use", "var": "s", "line": 12}]}]})
    gotdm = sorted((x.component, x.code) for x in ovdir2)
    if gotdm != [("dM", "OWN002")]:
        fails.append("§10 q2 direct call to agreeing-consume overloads should apply consume "
                     f"(dM OWN002), got {gotdm}")
    # (_merge_returns) overloaded FACTORY: every overload returns fresh, so a dropped result
    # leaks interprocedurally (OWN001 at the call) — the merge restores the `fresh` resolution
    # that dropping the overloaded name used to lose.
    checks += 1
    ovret = check_facts({"module": "M", "functions": [
        {"name": "C.F", "file": "F.cs",
         "body": [{"op": "acquire", "var": "r", "line": 1},
                  {"op": "return", "var": "r", "line": 2}]},
        {"name": "C.F", "file": "F.cs", "params": [{"name": "p", "line": 4}],
         "body": [{"op": "acquire", "var": "r", "line": 5},
                  {"op": "return", "var": "r", "line": 6}]},
        {"name": "fdrop", "file": "F.cs",
         "body": [{"op": "call", "callee": "C.F", "args": [], "result": "x", "line": 10}]}]})
    gotfr = sorted((x.component, x.code) for x in ovret)
    if gotfr != [("fdrop", "OWN001")]:
        fails.append("§10 q2 agreeing fresh overloaded factory: dropped result must leak "
                     f"(fdrop OWN001), got {gotfr}")
    # when overloads DISAGREE on the return (one fresh, one not), the merge degrades to a
    # non-fresh return, so a dropped result makes NO claim (precision-first: a real leak via
    # the fresh overload is a tolerated miss, never a fabricated acquire).
    checks += 1
    ovret2 = check_facts({"module": "M", "functions": [
        {"name": "C.G", "file": "F.cs",
         "body": [{"op": "acquire", "var": "r", "line": 1},
                  {"op": "return", "var": "r", "line": 2}]},                 # fresh
        {"name": "C.G", "file": "F.cs", "params": [{"name": "p", "line": 4}],
         "body": [{"op": "use", "var": "p", "line": 5}]},                    # no owned return
        {"name": "gdrop", "file": "F.cs",
         "body": [{"op": "call", "callee": "C.G", "args": [], "result": "x", "line": 10}]}]})
    if ovret2:
        fails.append("§10 q2 disagreeing-return overloads must make no fresh claim (silent), "
                     f"got {[(x.component, x.code) for x in ovret2]}")
    # (CodeRabbit) the overload channel matches on the CANONICAL name, so a `global::`-qualified
    # direct call to an overloaded method still applies the merged contract: both overloads
    # consume, so `global::C.M(s); release s` is release-after-consume OWN002 (raw-key matching
    # would have dropped the handoff and silently missed the double-discharge).
    checks += 1
    ovq = check_facts({"module": "M", "functions": [
        {"name": "C.M", "file": "F.cs", "params": [{"name": "a", "line": 1}],
         "body": [{"op": "release", "var": "a", "line": 2}]},
        {"name": "C.M", "file": "F.cs", "params": [{"name": "b", "line": 5}],
         "body": [{"op": "release", "var": "b", "line": 6}]},
        {"name": "dQ", "file": "F.cs",
         "body": [{"op": "acquire", "var": "s", "line": 10},
                  {"op": "call", "callee": "global::C.M", "args": ["s"], "line": 11},
                  {"op": "release", "var": "s", "line": 12}]}]})
    gotq = sorted((x.component, x.code) for x in ovq)
    if gotq != [("dQ", "OWN002")]:
        fails.append("§10 q2 qualified (global::) call to agreeing-consume overloads should "
                     f"apply the merged consume (dQ OWN002), got {gotq}")
    # --- P-005 D5.1b: the per-call-site ownership-contract channel. The extractor
    #     routes a call's per-argument ownership through fixed sink externs
    #     ($consume / $borrow / $borrow_mut) the bridge pre-declares, so an effect
    #     the callee's body cannot reveal (a BCL `leaveOpen: false`, an annotation)
    #     is checked through the SAME lower_call path — no new checker.
    # $consume takes ownership: a local acquired then handed to $consume has left, so
    # a later USE is OWN002 (anchored at the acquire, like every transitive handoff).
    checks += 1
    csink = check_facts({"module": "M", "functions": [
        {"name": "use_after_consume", "file": "F.cs",
         "body": [{"op": "acquire", "var": "x", "line": 10},
                  {"op": "call", "callee": "$consume", "args": ["x"], "line": 11},
                  {"op": "use", "var": "x", "line": 12}]}]})
    gotcs = [(x.component, x.line, x.code) for x in csink]
    if gotcs != [("use_after_consume", 10, "OWN002")]:
        fails.append("D5.1b $consume channel: use after a $consume handoff must be "
                     f"OWN002@10 (ownership left at the call), got {gotcs}")
    # releasing AFTER $consume double-discharges (the obligation already moved out).
    checks += 1
    crel = check_facts({"module": "M", "functions": [
        {"name": "release_after_consume", "file": "F.cs",
         "body": [{"op": "acquire", "var": "x", "line": 20},
                  {"op": "call", "callee": "$consume", "args": ["x"], "line": 21},
                  {"op": "release", "var": "x", "line": 22}]}]})
    gotcr = [(x.component, x.line, x.code) for x in crel]
    if gotcr != [("release_after_consume", 20, "OWN002")]:
        fails.append("D5.1b $consume channel: release after a $consume handoff must be "
                     f"OWN002@20, got {gotcr}")
    # $borrow only LENDS for the call: the caller keeps ownership, so a local handed
    # to $borrow and never released is still a leak (OWN001) — the channel does NOT
    # over-consume a borrow into a (silent) transfer.
    checks += 1
    bleak = check_facts({"module": "M", "functions": [
        {"name": "borrow_then_leak", "file": "F.cs",
         "body": [{"op": "acquire", "var": "x", "line": 30},
                  {"op": "call", "callee": "$borrow", "args": ["x"], "line": 31}]}]})
    gotbl = [(x.component, x.line, x.code) for x in bleak]
    if gotbl != [("borrow_then_leak", 30, "OWN001")]:
        fails.append("D5.1b $borrow channel: a borrowed-then-never-released local must "
                     f"still leak OWN001@30 (borrow keeps ownership), got {gotbl}")
    # and $borrow then releasing is clean — the loan is returned, the owner discharges.
    checks += 1
    bclean = check_facts({"module": "M", "functions": [
        {"name": "borrow_then_release", "file": "F.cs",
         "body": [{"op": "acquire", "var": "x", "line": 40},
                  {"op": "call", "callee": "$borrow", "args": ["x"], "line": 41},
                  {"op": "release", "var": "x", "line": 42}]}]})
    if bclean:
        fails.append("D5.1b $borrow channel: borrow-then-release must be clean, "
                     f"got {[(x.component, x.code) for x in bclean]}")
    # the DIRECT $borrow_mut channel keeps the exclusive loan: like $borrow, it lends
    # for the call and the caller keeps ownership, so a never-released local still
    # leaks (OWN001) and a released one is clean. (The transitive shortcut for
    # $borrow_mut is deliberately declined — the transfer lattice has no shared-vs-
    # exclusive axis, so a wrapper would silently downgrade it; see _SINK_PATH_ACTION.)
    checks += 1
    bmleak = check_facts({"module": "M", "functions": [
        {"name": "borrow_mut_leak", "file": "F.cs",
         "body": [{"op": "acquire", "var": "x", "line": 50},
                  {"op": "call", "callee": "$borrow_mut", "args": ["x"], "line": 51}]}]})
    gotbm = [(x.component, x.line, x.code) for x in bmleak]
    if gotbm != [("borrow_mut_leak", 50, "OWN001")]:
        fails.append("D5.1b $borrow_mut channel: a borrowed-then-never-released local "
                     f"must still leak OWN001@50 (exclusive loan keeps ownership), got {gotbm}")
    checks += 1
    bmclean = check_facts({"module": "M", "functions": [
        {"name": "borrow_mut_release", "file": "F.cs",
         "body": [{"op": "acquire", "var": "x", "line": 60},
                  {"op": "call", "callee": "$borrow_mut", "args": ["x"], "line": 61},
                  {"op": "release", "var": "x", "line": 62}]}]})
    if bmclean:
        fails.append("D5.1b $borrow_mut channel: borrow_mut-then-release must be clean, "
                     f"got {[(x.component, x.code) for x in bmclean]}")
    # the channel resolves TRANSITIVELY too: a param ONLY forwarded to $consume makes
    # the method a must-consumer (the solver reads the sink as a known transfer), so a
    # caller using its arg after the handoff is OWN002 — same as forwarding to a
    # first-party consumer, but sourced from the per-call channel.
    checks += 1
    ctrans = check_facts({"module": "M", "functions": [
        {"name": "wrap_consume", "file": "F.cs", "params": [{"name": "s", "line": 1}],
         "body": [{"op": "call", "callee": "$consume", "args": ["s"], "line": 2}]},
        {"name": "caller_t", "file": "F.cs",
         "body": [{"op": "acquire", "var": "s", "line": 10},
                  {"op": "call", "callee": "wrap_consume", "args": ["s"], "line": 11},
                  {"op": "use", "var": "s", "line": 12}]}]})
    gotct = [(x.component, x.line, x.code) for x in ctrans]
    if gotct != [("caller_t", 10, "OWN002")]:
        fails.append("D5.1b $consume channel must propagate transitively: a param "
                     f"forwarded to $consume makes the method consume, got {gotct}")
    # --- P-005 D5.2 (T1): a `fresh`-returning factory call becomes an acquire SITE.
    #     A method that acquires a local and returns it (`make`) has returnsOwned=fresh;
    #     a caller binding its result (`var r = make()`) now owns `r`, so the existing
    #     leak / double-release / use-after checks apply to the call site. This is the
    #     factory-leak class — silently lost before D5.2.
    _MAKE = {"name": "make", "file": "T1.cs",
             "body": [{"op": "acquire", "var": "x", "line": 1},
                      {"op": "return", "var": "x", "line": 2}]}
    # the result is never disposed -> the factory call site leaks (OWN001 @ the call).
    checks += 1
    fl = check_facts({"module": "M", "functions": [_MAKE,
        {"name": "caller", "file": "T1.cs",
         "body": [{"op": "call", "callee": "make", "args": [], "result": "r",
                   "line": 10}]}]})
    gotfl = [(x.component, x.line, x.code) for x in fl]
    if gotfl != [("caller", 10, "OWN001")]:
        fails.append("D5.2 T1: a fresh-returning factory whose result is never disposed "
                     f"must leak OWN001@10 at the call site, got {gotfl}")
    # the same result, disposed, is clean (the obligation is discharged).
    checks += 1
    fok = check_facts({"module": "M", "functions": [_MAKE,
        {"name": "caller_ok", "file": "T1.cs",
         "body": [{"op": "call", "callee": "make", "args": [], "result": "r", "line": 10},
                  {"op": "release", "var": "r", "line": 11}]}]})
    if fok:
        fails.append("D5.2 T1: a factory result that IS disposed must be clean, "
                     f"got {[(x.component, x.code) for x in fok]}")
    # using the factory result after dispose is use-after-release (OWN002 @ the call).
    checks += 1
    fuar = check_facts({"module": "M", "functions": [_MAKE,
        {"name": "caller_uar", "file": "T1.cs",
         "body": [{"op": "call", "callee": "make", "args": [], "result": "r", "line": 10},
                  {"op": "release", "var": "r", "line": 11},
                  {"op": "use", "var": "r", "line": 12}]}]})
    gotuar = [(x.component, x.line, x.code) for x in fuar]
    if gotuar != [("caller_uar", 10, "OWN002")]:
        fails.append("D5.2 T1: using a factory result after dispose must be OWN002@10, "
                     f"got {gotuar}")
    # fresh propagates through a forward-return factory-of-factory: `relay` returns the
    # result of `make`, so `relay` is fresh too, and a caller leaking it is OWN001.
    checks += 1
    ff = check_facts({"module": "M", "functions": [_MAKE,
        {"name": "relay", "file": "T1.cs",
         "body": [{"op": "call", "callee": "make", "args": [], "result": "t", "line": 1},
                  {"op": "return", "var": "t", "line": 2}]},
        {"name": "caller_ff", "file": "T1.cs",
         "body": [{"op": "call", "callee": "relay", "args": [], "result": "r",
                   "line": 10}]}]})
    gotff = [(x.component, x.line, x.code) for x in ff]
    if gotff != [("caller_ff", 10, "OWN001")]:
        fails.append("D5.2 T1: fresh must propagate through a forward-return factory-of-"
                     f"factory, so the caller leaks OWN001@10, got {gotff}")
    # PRECISION: a method that returns a PARAMETER is NOT fresh (that is the wrap/alias
    # case, T4/D5.4). `ident(s){ return s }` must not make the caller acquire `r`, and
    # must not consume the arg — so acquire/call/release of `a` stays clean and silent.
    checks += 1
    pr = check_facts({"module": "M", "functions": [
        {"name": "ident", "file": "T1.cs", "params": [{"name": "s", "line": 1}],
         "body": [{"op": "return", "var": "s", "line": 2}]},
        {"name": "caller_pr", "file": "T1.cs",
         "body": [{"op": "acquire", "var": "a", "line": 10},
                  {"op": "call", "callee": "ident", "args": ["a"], "result": "r",
                   "line": 11},
                  {"op": "release", "var": "a", "line": 12}]}]})
    if pr:
        gotpr = [(x.component, x.code) for x in pr]
        fails.append("D5.2 T1: returning a parameter is not `fresh` (no false acquire of "
                     f"the result, no consume of the arg), got {gotpr}")
    # ROBUSTNESS (real extraction): a `call` to a callee NOT in functions[] — a BCL /
    # extension method the extractor surfaced (e.g. `GetRequiredService`) — has no
    # signature, so it must be dropped (no Call, no acquire), NEVER raise OWN040. The
    # bridge gates the Call on a resolvable callee and skips OWN040 belt-and-suspenders.
    checks += 1
    try:
        unk = check_facts({"module": "M", "functions": [
            {"name": "Caller.Use", "file": "T1.cs",
             "body": [{"op": "call", "callee": "Ext.GetRequiredService", "args": [],
                       "result": "svc", "line": 5}]}]})
        if unk:
            fails.append("D5.2: a call to an unknown callee must make no claim (no finding), "
                         f"got {[(x.component, x.code) for x in unk]}")
    except OwnIRError as e:
        fails.append(f"D5.2: a call to an unknown callee must not crash (OWN040), got {e!r}")
    # Tier B (D5.3 / P1a): a curated BCL *factory* (`File.OpenRead` &c.) returns an owned
    # IDisposable even with no first-party body, so a leaked `var s = File.OpenRead(p)` is
    # OWN001 AT the factory call (invisible before this table) — the producer half of the
    # boundary contract. Contrast the unknown-callee case just above, which makes no claim.
    def _bcl(body: list) -> list:
        return check_facts({"module": "M", "functions": [
            {"name": "Svc.Do", "file": "Bcl.cs", "body": body}]})
    checks += 1
    bleak = [(x.code, x.line, x.kind) for x in _bcl(
        [{"op": "call", "callee": "File.OpenRead", "args": ["p"], "result": "s", "line": 5}])]
    if bleak != [("OWN001", 5, "disposable")]:
        fails.append(f"Tier B: a leaked BCL factory result must be OWN001@5 disposable, "
                     f"got {bleak}")
    checks += 1
    if _bcl([{"op": "call", "callee": "File.OpenRead", "args": ["p"], "result": "s", "line": 5},
             {"op": "release", "var": "s", "line": 6}]):
        fails.append("Tier B: a disposed BCL factory result must be clean (silent)")
    checks += 1
    buar = [(x.code, x.line) for x in _bcl(
        [{"op": "call", "callee": "File.OpenRead", "args": ["p"], "result": "s", "line": 5},
         {"op": "release", "var": "s", "line": 6},
         {"op": "use", "var": "s", "line": 7}])]
    if buar != [("OWN002", 5)]:
        fails.append(f"Tier B: using a BCL factory result after dispose must be OWN002@5, "
                     f"got {buar}")
    checks += 1
    # a namespace-qualified callee resolves on its last two segments (`Type.Method`).
    nsq = [(x.code, x.line) for x in _bcl(
        [{"op": "call", "callee": "System.IO.File.Create", "args": ["p"],
          "result": "s", "line": 9}])]
    if nsq != [("OWN001", 9)]:
        fails.append(f"Tier B: a namespace-qualified BCL factory must resolve, got {nsq}")
    checks += 1
    # a non-disposable BCL method (`File.ReadAllText` -> string) is NOT a factory — no false
    # acquire of its result, stays silent (precision-first: the table is owned-returns only).
    if _bcl([{"op": "call", "callee": "File.ReadAllText", "args": ["p"],
              "result": "t", "line": 3}]):
        fails.append("Tier B: a non-disposable BCL method must not be treated as a factory")
    checks += 1
    # PRECISION (Codex): a same-named factory in ANOTHER namespace is NOT System.IO.File, so
    # the match must not be a loose suffix — only bare `File.X` and `System.IO.File.X` count.
    # A `MyCompany.File.OpenRead` returning a plain value must NOT fabricate a false OWN001.
    if _bcl([{"op": "call", "callee": "MyCompany.File.OpenRead", "args": ["p"],
              "result": "s", "line": 5}]):
        fails.append("Tier B precision: a non-System.IO `*.File.OpenRead` must NOT match")
    checks += 1
    # a `global::`-qualified System.IO.File factory IS the BCL identity (the qualifier is
    # stripped); a `global::`-qualified non-System.IO look-alike still must NOT match.
    gq = [(x.code, x.line) for x in _bcl([{"op": "call",
           "callee": "global::System.IO.File.OpenRead", "args": ["p"],
           "result": "s", "line": 4}])]
    if gq != [("OWN001", 4)]:
        fails.append(f"Tier B: a `global::System.IO.File.*` factory must match, got {gq}")
    if _bcl([{"op": "call", "callee": "global::MyCompany.File.OpenRead", "args": ["p"],
              "result": "s", "line": 4}]):
        fails.append("Tier B precision: `global::`-qualified non-System.IO must NOT match")
    # P1a (stdlib pack): more curated owned-returning factories. A dropped XmlReader/XmlWriter/
    # JsonDocument result leaks at the factory call (OWN001), the same producer-side contract as
    # File.Open* — both the bare `Type.Method` and the namespace-qualified identity resolve.
    for fresh_callee, ln in (("XmlReader.Create", 5),
                             ("System.Xml.XmlReader.Create", 6),
                             ("XmlWriter.Create", 7),
                             ("System.Xml.XmlWriter.Create", 8),
                             ("JsonDocument.Parse", 9),
                             ("System.Text.Json.JsonDocument.Parse", 10)):
        checks += 1
        leak = [(x.code, x.line) for x in _bcl(
            [{"op": "call", "callee": fresh_callee, "args": ["a"], "result": "s", "line": ln}])]
        if leak != [("OWN001", ln)]:
            fails.append(f"P1a: a leaked `{fresh_callee}` result must be OWN001@{ln}, got {leak}")
    # disposing the P1a factory result is clean (no false leak), proving it is a real acquire.
    checks += 1
    if _bcl([{"op": "call", "callee": "XmlReader.Create", "args": ["a"], "result": "s", "line": 5},
             {"op": "release", "var": "s", "line": 6}]):
        fails.append("P1a: a disposed XmlReader.Create result must be clean (silent)")
    checks += 1
    # OVERRIDE (Codex): a first-party summary is authoritative — a first-party `File.OpenRead`
    # that returns its parameter is NOT fresh, so a caller dropping its result is clean; the
    # table must not fabricate ownership for a callee whose body we can see.
    ov_fp = check_facts({"module": "M", "functions": [
        {"name": "File.OpenRead", "file": "B.cs", "params": [{"name": "x", "line": 1}],
         "body": [{"op": "return", "var": "x", "line": 2}]},
        {"name": "Caller", "file": "B.cs", "body": [
            {"op": "acquire", "var": "a", "line": 10},
            {"op": "call", "callee": "File.OpenRead", "args": ["a"],
             "result": "r", "line": 11},
            {"op": "release", "var": "a", "line": 12}]}]})
    if ov_fp:
        fails.append(f"Tier B: a first-party summary must override the BCL table, "
                     f"got {[(x.component, x.code) for x in ov_fp]}")
    checks += 1
    # RECALL (Codex): a first-party wrapper that returns a BCL factory result is itself fresh,
    # so a caller dropping `Make()` leaks OWN001 — the return skeleton propagates BCL freshness
    # rather than degrading to a `forward` to the external factory (-> unknown -> invisible).
    wrap = [(x.component, x.line, x.code) for x in check_facts({"module": "M", "functions": [
        {"name": "Make", "file": "B.cs", "body": [
            {"op": "call", "callee": "File.OpenRead", "args": ["p"],
             "result": "s", "line": 2},
            {"op": "return", "var": "s", "line": 3}]},
        {"name": "Caller2", "file": "B.cs", "body": [
            {"op": "call", "callee": "Make", "args": [], "result": "r", "line": 10}]}]})]
    if wrap != [("Caller2", 10, "OWN001")]:
        fails.append(f"Tier B: a wrapper returning a BCL factory result must be fresh "
                     f"(caller leak OWN001@10), got {wrap}")
    checks += 1
    # D5.3 breadth: a crypto algorithm `Create()` is an owned IDisposable factory — a leaked
    # `using var sha = SHA256.Create()` is OWN001; disposed is clean; used after dispose is
    # OWN002. Resolves bare and under System.Security.Cryptography.
    cleak = [(x.code, x.line) for x in _bcl(
        [{"op": "call", "callee": "SHA256.Create", "args": [], "result": "h", "line": 5}])]
    if cleak != [("OWN001", 5)]:
        fails.append(f"Tier B: a leaked crypto Create() factory must be OWN001@5, got {cleak}")
    checks += 1
    if _bcl([{"op": "call", "callee": "Aes.Create", "args": [], "result": "a", "line": 5},
             {"op": "release", "var": "a", "line": 6}]):
        fails.append("Tier B: a disposed crypto Create() factory must be clean")
    checks += 1
    cfqn = [(x.code, x.line) for x in _bcl([{"op": "call",
             "callee": "System.Security.Cryptography.RSA.Create", "args": [],
             "result": "r", "line": 7}])]
    if cfqn != [("OWN001", 7)]:
        fails.append(f"Tier B: a namespace-qualified crypto factory must resolve, got {cfqn}")
    checks += 1
    # a same-named crypto type in ANOTHER namespace must NOT match (precision).
    if _bcl([{"op": "call", "callee": "MyCrypto.SHA256.Create", "args": [],
              "result": "h", "line": 5}]):
        fails.append("Tier B precision: a non-System crypto `*.SHA256.Create` must NOT match")
    checks += 1
    # `Process.Start` is deliberately EXCLUDED — it is a static owned-Process factory but ALSO
    # an instance method returning `bool`, so a bare match would fabricate ownership for the
    # instance form. The table must make no claim on it.
    if _bcl([{"op": "call", "callee": "Process.Start", "args": ["x"], "result": "p", "line": 5}]):
        fails.append("Tier B precision: overload-ambiguous `Process.Start` must NOT be a factory")
    checks += 1
    # OVERRIDE through a WRAPPER (Codex P2): Tier A beats Tier B even one hop removed. A
    # first-party method named `SHA256.Create` that returns its parameter is NOT fresh; a
    # wrapper `Make` that returns `SHA256.Create(x)` must inherit THAT (non-fresh) summary,
    # not the bare BCL table — so a caller dropping `Make()` is clean. Before the fix the
    # wrapper's return skeleton short-circuited to `fresh` via the BCL name match, fabricating
    # OWN001 on the caller even though the same-named callee has a visible (non-owning) body.
    ov_wrap = check_facts({"module": "M", "functions": [
        {"name": "SHA256.Create", "file": "B.cs", "params": [{"name": "x", "line": 1}],
         "body": [{"op": "return", "var": "x", "line": 2}]},
        {"name": "Make", "file": "B.cs", "params": [{"name": "x", "line": 5}],
         "body": [{"op": "call", "callee": "SHA256.Create", "args": ["x"],
                   "result": "r", "line": 6},
                  {"op": "return", "var": "r", "line": 7}]},
        {"name": "Caller3", "file": "B.cs", "body": [
            {"op": "acquire", "var": "a", "line": 9},
            {"op": "call", "callee": "Make", "args": ["a"], "result": "m", "line": 10},
            {"op": "release", "var": "a", "line": 11}]}]})
    if ov_wrap:
        fails.append("Tier B: a wrapper around a same-named first-party method must inherit "
                     "its (non-fresh) summary, not the BCL table, got "
                     f"{[(x.component, x.code) for x in ov_wrap]}")
    checks += 1
    # OVERRIDE on a DIRECT call to an OVERLOADED first-party method (CodeRabbit): an
    # overloaded source method named `SHA256.Create` is dropped from `mos` (no unique
    # summary), but it is still first-party — the BCL table must not fire for it, or a
    # dropped `var h = SHA256.Create(a)` would be a false OWN001 on a direct call while the
    # wrapper path stays silent. Tier A's reach covers dropped overloads too: no claim.
    ov_overload = check_facts({"module": "M", "functions": [
        {"name": "SHA256.Create", "file": "B.cs", "params": [{"name": "a", "line": 1}],
         "body": [{"op": "return", "var": "a", "line": 2}]},
        {"name": "SHA256.Create", "file": "B.cs",
         "params": [{"name": "a", "line": 3}, {"name": "b", "line": 3}],
         "body": [{"op": "return", "var": "a", "line": 4}]},
        {"name": "Caller4", "file": "B.cs", "body": [
            {"op": "call", "callee": "SHA256.Create", "args": [], "result": "h", "line": 9}]}]})
    if ov_overload:
        fails.append("Tier B: an overloaded (dropped) first-party method with a BCL name must "
                     "not fall back to the BCL table on a direct call, got "
                     f"{[(x.component, x.code) for x in ov_overload]}")
    checks += 1
    # OVERRIDE survives `global::` qualification (CodeRabbit): the BCL matcher strips
    # `global::`, so the first-party check must too — else a source `…SHA256.Create` called as
    # `global::…SHA256.Create` misses both `mos` and `first_party` and falls through to the
    # table as fresh. A first-party (non-fresh) method invoked global-qualified stays silent.
    ov_global = check_facts({"module": "M", "functions": [
        {"name": "System.Security.Cryptography.SHA256.Create", "file": "B.cs",
         "params": [{"name": "a", "line": 1}],
         "body": [{"op": "return", "var": "a", "line": 2}]},
        {"name": "Caller5", "file": "B.cs", "body": [
            {"op": "call",
             "callee": "global::System.Security.Cryptography.SHA256.Create",
             "args": [], "result": "h", "line": 9}]}]})
    if ov_global:
        fails.append("Tier B: a `global::`-qualified call to a first-party method must resolve "
                     "to its (non-fresh) summary, not the BCL table, got "
                     f"{[(x.component, x.code) for x in ov_global]}")
    # OVERWRITE kills the prior binding (CodeRabbit): `acquire x; x = Unknown(); release x`
    # — the call's result reuses an owned local and the call is dropped (unknown callee),
    # so the ORIGINAL x leaks (its reference is lost), not read as clean. The release after
    # must not resolve to the dead handle.
    checks += 1
    ov = check_facts({"module": "M", "functions": [
        {"name": "C.M", "file": "T1.cs",
         "body": [{"op": "acquire", "var": "x", "line": 1},
                  {"op": "call", "callee": "Ext.Unknown", "args": [], "result": "x", "line": 2},
                  {"op": "release", "var": "x", "line": 3}]}]})
    gotov = [(x.component, x.line, x.code) for x in ov]
    if gotov != [("C.M", 1, "OWN001")]:
        fails.append("D5.2: a call result overwriting an owned local must leak the original "
                     f"(OWN001@1), not read as clean, got {gotov}")
    # the factory acquire must fire inside CONTROL FLOW too: a fresh-returning call in
    # an `if` branch whose result is never disposed leaks, exactly like a top-level one.
    # (Codex P2: the recursive _lower_flow calls must thread `mos` into nested bodies,
    # else the D5.2 acquire is silently skipped in branch/loop bodies.)
    checks += 1
    fif = check_facts({"module": "M", "functions": [_MAKE,
        {"name": "caller_if", "file": "T1.cs",
         "body": [{"op": "if", "line": 9, "then": [
             {"op": "call", "callee": "make", "args": [], "result": "r", "line": 10}],
             "else": []}]}]})
    gotfif = [(x.component, x.line, x.code) for x in fif]
    if gotfif != [("caller_if", 10, "OWN001")]:
        fails.append("D5.2 T1: a fresh factory call inside an `if` branch must also leak "
                     f"OWN001@10 (mos threaded into nested flow), got {gotfif}")
    # PRECISION (CodeRabbit): a returned local that is also a call RESULT is mixed-origin,
    # not provably `fresh`. `mixed` acquires x, then overwrites it with `other`'s (non-
    # owned) result, and returns it — `returned == acquired == {x}` would wrongly read as
    # fresh, so a caller acquiring its dropped result would fabricate OWN001. The result
    # must NOT be fresh -> the caller stays silent.
    checks += 1
    mxd = check_facts({"module": "M", "functions": [
        {"name": "other", "file": "T1.cs", "body": []},
        {"name": "mixed", "file": "T1.cs",
         "body": [{"op": "acquire", "var": "x", "line": 1},
                  {"op": "call", "callee": "other", "args": [], "result": "x", "line": 2},
                  {"op": "return", "var": "x", "line": 3}]},
        {"name": "caller_mx", "file": "T1.cs",
         "body": [{"op": "call", "callee": "mixed", "args": [], "result": "r",
                   "line": 10}]}]})
    gotmxd = [(x.component, x.code) for x in mxd if x.component == "caller_mx"]
    if gotmxd:
        fails.append("D5.2 T1: a mixed-origin return (acquired AND a call result) is not "
                     f"`fresh`, so the caller's dropped result must be silent, got {gotmxd}")
    # PRECISION (Codex): `fresh` requires EVERY return path to be owned. A method that
    # returns an acquired local on one branch but a bare `return` (null / non-owned) on
    # another is not uniformly fresh — a caller dropping its result must NOT be charged a
    # leak on the null path. `maybe_make` must not be fresh -> caller_bare stays silent.
    checks += 1
    bare = check_facts({"module": "M", "functions": [
        {"name": "maybe_make", "file": "T1.cs",
         "body": [{"op": "if", "line": 1,
                   "then": [{"op": "acquire", "var": "x", "line": 2},
                            {"op": "return", "var": "x", "line": 3}],
                   "else": [{"op": "return", "line": 4}]}]},
        {"name": "caller_bare", "file": "T1.cs",
         "body": [{"op": "call", "callee": "maybe_make", "args": [], "result": "r",
                   "line": 10}]}]})
    gotbare = [(x.component, x.code) for x in bare if x.component == "caller_bare"]
    if gotbare:
        fails.append("D5.2 T1: a method with a non-owned (`return null`) path is not "
                     f"`fresh`, so a caller's dropped result must be silent, got {gotbare}")
    # BRIDGE BRANCH-SCOPE FIX. A local acquired in BOTH branches of an `if` and released
    # AFTER the merge used to crash: the bridge emitted each synthetic `Let` *inside* its
    # branch block, so the post-merge `release` referenced an out-of-scope handle -> the
    # core reported OWN030 (undefined name) and `check_facts` raised OwnIRError. The bridge
    # now HOISTS such cross-branch locals to the function's outer scope (declared once,
    # in-branch acquires skipped), so a balanced release is CLEAN. `branch_merge` is the
    # exact pre-existing repro (a PLAIN `acquire`, no factory path) — must not crash, no
    # findings. (Codex P2 on #116.)
    checks += 1
    try:
        bmf = check_facts({"module": "M", "functions": [
            {"name": "branch_merge", "file": "T1.cs",
             "body": [{"op": "if", "line": 1,
                       "then": [{"op": "acquire", "var": "r", "line": 2}],
                       "else": [{"op": "acquire", "var": "r", "line": 3}]},
                      {"op": "release", "var": "r", "line": 4}]}]})
        if bmf:
            fails.append("bridge branch-scope: a cross-branch acquire released after the "
                         f"merge must be CLEAN, got {[(x.component, x.code) for x in bmf]}")
    except OwnIRError as e:
        fails.append(f"bridge branch-scope: cross-branch acquire still crashes ({e})")
    # the leak is still caught when the cross-branch local is NOT released: hoisting makes
    # the acquire unconditional, so an undischarged one is OWN001 (no false-clean).
    checks += 1
    bml = check_facts({"module": "M", "functions": [
        {"name": "branch_leak", "file": "T1.cs",
         "body": [{"op": "if", "line": 1,
                   "then": [{"op": "acquire", "var": "r", "line": 2}],
                   "else": [{"op": "acquire", "var": "r", "line": 3}]},
                  {"op": "use", "var": "r", "line": 4}]}]})
    gotbml = [(x.component, x.code) for x in bml]
    if gotbml != [("branch_leak", "OWN001")]:
        fails.append("bridge branch-scope: a cross-branch acquire that is used but never "
                     f"released must still leak OWN001, got {gotbml}")
    # and the factory-result form (D5.2 acquire inside a branch) is hoisted too: a fresh
    # call result assigned in both branches and released after the merge is CLEAN.
    checks += 1
    try:
        bmfr = check_facts({"module": "M", "functions": [_MAKE,
            {"name": "branch_factory", "file": "T1.cs",
             "body": [{"op": "if", "line": 1,
                       "then": [{"op": "call", "callee": "make", "args": [], "result": "r",
                                 "line": 2}],
                       "else": [{"op": "call", "callee": "make", "args": [], "result": "r",
                                 "line": 3}]},
                      {"op": "release", "var": "r", "line": 4}]}]})
        if bmfr:
            fails.append("bridge branch-scope: a cross-branch FACTORY result released after "
                         f"the merge must be CLEAN, got {[(x.component, x.code) for x in bmfr]}")
    except OwnIRError as e:
        fails.append(f"bridge branch-scope: cross-branch factory result still crashes ({e})")
    # NARROWER REMAINING LIMITATION (xfail-style lock). When the reference is itself at
    # depth >= 1 (acquired at depth 2 inside a nested `if`, released at depth 1 in the
    # enclosing block), function-top is NOT the common-dominator scope, so the depth-0
    # hoist deliberately does not fire — and the original OWN030 -> OwnIRError still
    # occurs. The correct fix is to hoist to the common-dominator block; tracked for a
    # follow-up. This lock asserts the current raise and flips when that lands.
    checks += 1
    nst_raised = False
    try:
        check_facts({"module": "M", "functions": [
            {"name": "nested_branch", "file": "T1.cs",
             "body": [{"op": "if", "line": 1, "else": [],
                       "then": [{"op": "if", "line": 2, "else": [],
                                 "then": [{"op": "acquire", "var": "r", "line": 3}]},
                                {"op": "release", "var": "r", "line": 4}]}]}]})
    except OwnIRError:
        nst_raised = True
    if not nst_raised:
        fails.append("bridge branch-scope: nested cross-branch acquire no longer raises — the "
                     "common-dominator hoist has landed; make this CLEAN and flip this lock")
    # LOOP EXCLUSION (Codex P1): the hoist is for mutually-exclusive `if` branches only.
    # A `while` body is cumulative, so hoisting `while { acquire r }; release r` to one
    # acquire would HIDE the per-iteration leak (a false-clean). Loop-acquired locals are
    # excluded, so this keeps its pre-existing LOUD behaviour (OWN030 -> OwnIRError) rather
    # than silently returning no findings. A loop-aware model is a separate follow-up; this
    # lock asserts the raise (NOT a false-clean) and flips when that model lands.
    checks += 1
    loop_raised = False
    try:
        check_facts({"module": "M", "functions": [
            {"name": "loop_acq", "file": "T1.cs",
             "body": [{"op": "while", "line": 1,
                       "body": [{"op": "acquire", "var": "r", "line": 2}]},
                      {"op": "release", "var": "r", "line": 3}]}]})
    except OwnIRError:
        loop_raised = True
    if not loop_raised:
        fails.append("bridge branch-scope: a while-body acquire released after the loop must "
                     "NOT be silently hoisted to clean — it stays loud until a loop-aware model "
                     "lands; got no raise (false-clean or premature loop hoist)")
    # SAFETY (CodeRabbit Major): the hoist must NOT fire when a branch early-`return`s on a
    # path that did not acquire the local — an unconditional hoisted acquire would leak on
    # that path, a FALSE OWN001. `guard` (`if c: acquire r else: return; release r`) is
    # clean C# (else returns, r never acquired there). `_branch_hoist_safe` blocks the hoist,
    # so this stays the pre-existing loud raise — never a fabricated OWN001.
    checks += 1
    guard_ok = False
    try:
        gf = check_facts({"module": "M", "functions": [
            {"name": "guard", "file": "T1.cs",
             "body": [{"op": "if", "line": 1,
                       "then": [{"op": "acquire", "var": "r", "line": 2}],
                       "else": [{"op": "return", "line": 3}]},
                      {"op": "release", "var": "r", "line": 4}]}]})
        guard_ok = not gf  # if it lowered, it must NOT fabricate a finding
    except OwnIRError:
        guard_ok = True  # not hoisted -> loud raise, never a false OWN001
    if not guard_ok:
        fails.append("bridge branch-scope: an early-return branch must not be hoisted into a "
                     "fabricated OWN001 (the hoist safety predicate must block it)")
    # a one-branch acquire with NO early return IS safe to hoist (else falls through to the
    # release; null-safe dispose). It must be CLEAN, not crash.
    checks += 1
    try:
        ob = check_facts({"module": "M", "functions": [
            {"name": "one_branch", "file": "T1.cs",
             "body": [{"op": "if", "line": 1, "else": [],
                       "then": [{"op": "acquire", "var": "r", "line": 2}]},
                      {"op": "release", "var": "r", "line": 3}]}]})
        if ob:
            gotob = [(x.component, x.code) for x in ob]
            fails.append("bridge branch-scope: a one-branch acquire (no early return) released "
                         f"after the merge must be CLEAN, got {gotob}")
    except OwnIRError as e:
        fails.append(f"bridge branch-scope: a safe one-branch acquire must not crash ({e!r})")
    # a hoisted ArrayPool rent keeps its `pool` kind: a cross-branch Rent that is never
    # released leaks as a POOLED buffer (OWN025-style wording), not a generic disposable.
    # (CodeRabbit: the hoist must preserve acquire `kind`.) Asserted via the leak being
    # tagged pooled in its structured finding.
    checks += 1
    pl = check_facts({"module": "M", "functions": [
        {"name": "pool_branch", "file": "T1.cs",
         "body": [{"op": "if", "line": 1,
                   "then": [{"op": "acquire", "var": "r", "kind": "pool", "line": 2}],
                   "else": [{"op": "acquire", "var": "r", "kind": "pool", "line": 3}]},
                  {"op": "use", "var": "r", "line": 4}]}]})
    # assert the structured kind, not wording: dropping the pool flag would lower the
    # hoisted handle to a generic "disposable" (CodeRabbit).
    gotpl = [(x.code, x.kind) for x in pl]
    if gotpl != [("OWN001", "pooled buffer")]:
        fails.append("bridge branch-scope: a hoisted ArrayPool rent that leaks must stay tagged "
                     f"kind='pooled buffer' (kind preserved through the hoist), got {gotpl}")
    # --- P-005 D5.4 (T4 wrap/adopt): the `alias_join` flow op. `var w` becomes a NEW
    #     owning handle on the SAME resource obligation as `src` (a factory returning a
    #     wrapper of `src`, or a ctor adopting `src` into an owning field — T4a ≡ T4b).
    #     Errors are evaluated per-RID, so disposing EITHER alias discharges the one
    #     resource and disposing BOTH is a double-dispose. This is the Dapper/Polly
    #     wrapper-adoption shape modelled explicitly. (The extractor recognisers that
    #     EMIT this op land in D5.4 step 2; here the op is driven by synthetic facts.)
    #
    # disposing the wrapper alone discharges the obligation for both -> clean.
    checks += 1
    aw = check_facts({"module": "M", "functions": [
        {"name": "adopt_release_wrapper", "file": "T4.cs",
         "body": [{"op": "acquire", "var": "inner", "line": 1},
                  {"op": "alias_join", "var": "w", "src": "inner", "line": 2},
                  {"op": "release", "var": "w", "line": 3}]}]})
    if aw:
        fails.append("D5.4 T4: releasing the wrapper alias must discharge the shared "
                     f"obligation (clean), got {[(x.component, x.code) for x in aw]}")
    # disposing the inner directly (the Dapper dispose-the-inner path) is ALSO clean —
    # the alias set is satisfied through any member.
    checks += 1
    ai = check_facts({"module": "M", "functions": [
        {"name": "adopt_release_inner", "file": "T4.cs",
         "body": [{"op": "acquire", "var": "inner", "line": 1},
                  {"op": "alias_join", "var": "w", "src": "inner", "line": 2},
                  {"op": "release", "var": "inner", "line": 3}]}]})
    if ai:
        fails.append("D5.4 T4: releasing the inner directly must also discharge the shared "
                     f"obligation (clean), got {[(x.component, x.code) for x in ai]}")
    # dropping BOTH (neither released) leaks the ONE underlying resource exactly ONCE,
    # not once per alias — per-RID leak evaluation.
    checks += 1
    al = check_facts({"module": "M", "functions": [
        {"name": "adopt_leak", "file": "T4.cs",
         "body": [{"op": "acquire", "var": "inner", "line": 1},
                  {"op": "alias_join", "var": "w", "src": "inner", "line": 2}]}]})
    gotal = [(x.component, x.line, x.code) for x in al]
    if gotal != [("adopt_leak", 1, "OWN001")]:
        fails.append("D5.4 T4: dropping both aliases must leak the shared resource ONCE "
                     f"(OWN001@1, attributed to the inner), got {gotal}")
    # releasing BOTH aliases is a double-dispose (OWN003) — the second release hits an
    # already-Released RID through the other handle.
    checks += 1
    ad = check_facts({"module": "M", "functions": [
        {"name": "adopt_double", "file": "T4.cs",
         "body": [{"op": "acquire", "var": "inner", "line": 1},
                  {"op": "alias_join", "var": "w", "src": "inner", "line": 2},
                  {"op": "release", "var": "inner", "line": 3},
                  {"op": "release", "var": "w", "line": 4}]}]})
    # the finding anchors at the shared resource's origin (the `inner` acquire, line 1) —
    # the bridge remaps every flow-local diagnostic back to its acquire site, as the D5.2
    # use-after case does; the flow slice carries the release path.
    gotad = [(x.line, x.code) for x in ad]
    if gotad != [(1, "OWN003")]:
        fails.append("D5.4 T4: releasing both aliases must be a double-dispose (OWN003, "
                     f"anchored at the inner acquire @1), got {gotad}")
    # using an alias after the resource was released (through the OTHER handle) is a
    # use-after-release (OWN002).
    checks += 1
    au = check_facts({"module": "M", "functions": [
        {"name": "adopt_uar", "file": "T4.cs",
         "body": [{"op": "acquire", "var": "inner", "line": 1},
                  {"op": "alias_join", "var": "w", "src": "inner", "line": 2},
                  {"op": "release", "var": "w", "line": 3},
                  {"op": "use", "var": "inner", "line": 4}]}]})
    gotau = [(x.line, x.code) for x in au]
    if gotau != [(1, "OWN002")]:
        fails.append("D5.4 T4: using an alias after release through the other handle must be "
                     f"OWN002 (anchored at the inner acquire @1), got {gotau}")
    # PRECISION: an `alias_join` whose `src` is NOT a tracked local makes NO claim — no
    # acquire is fabricated for the wrapper, so a later release of it is silently dropped
    # (never a phantom OWN003/OWN002). Optimistic-silent, per the v1 must-only rule.
    checks += 1
    an = check_facts({"module": "M", "functions": [
        {"name": "adopt_unknown_src", "file": "T4.cs",
         "body": [{"op": "alias_join", "var": "w", "src": "ghost", "line": 2},
                  {"op": "release", "var": "w", "line": 3}]}]})
    if an:
        fails.append("D5.4 T4: an alias_join over an untracked src must make no claim "
                     f"(silent), got {[(x.component, x.code) for x in an]}")
    # THE PRECISION WIN (§11 Dapper shape): a factory acquires `inner` as a LOCAL, wraps it
    # (`w` aliases inner), and RETURNS the wrapper. `inner` is dropped as a local, but its
    # obligation escaped through `w` — so per-RID leak evaluation sees the shared RID escape
    # and reports NO leak. Without the alias set this dropped local would be a false OWN001;
    # this is the own-only-0-with-a-reason case the whole D5.4 model exists to model.
    checks += 1
    rw = check_facts({"module": "M", "functions": [
        {"name": "Wrap.Create", "file": "T4.cs",
         "body": [{"op": "acquire", "var": "inner", "line": 1},
                  {"op": "alias_join", "var": "w", "src": "inner", "line": 2},
                  {"op": "return", "var": "w", "line": 3}]}]})
    if rw:
        gotrw = [(x.component, x.code) for x in rw]
        fails.append("D5.4 T4: returning the wrapper escapes the shared obligation, so the "
                     f"dropped inner local must NOT leak, got {gotrw}")
    # OVERWRITE kills the prior binding even when the new alias is UNTRACKED (Codex P2):
    # `acquire w; alias_join w <- ghost; release w` overwrites `w` with an alias whose src
    # is not tracked. The original `w` obligation is lost (it leaks OWN001@1); the later
    # `release w` must NOT resolve to the dead handle and silently discharge it.
    checks += 1
    aov = check_facts({"module": "M", "functions": [
        {"name": "C.M", "file": "T4.cs",
         "body": [{"op": "acquire", "var": "w", "line": 1},
                  {"op": "alias_join", "var": "w", "src": "ghost", "line": 2},
                  {"op": "release", "var": "w", "line": 3}]}]})
    gotaov = [(x.line, x.code) for x in aov]
    if gotaov != [(1, "OWN001")]:
        fails.append("D5.4 T4: an alias_join overwriting an owned local with an UNTRACKED src "
                     f"must leak the original (OWN001@1), not read clean, got {gotaov}")
    # POOL005: a full-length view of a pooled buffer (`overspan` flow fact) raises
    # OWN025 at the VIEW site (line 12, not the Rent site), tagged a pooled buffer;
    # the buffer is still returned, so there is no OWN001 leak. Routes through the
    # same core op the `.own` `overspan` statement lowers to.
    checks += 1
    osp = check_facts({"module": "M", "functions": [
        {"name": "Framer.Frame", "file": "Framer.cs",
         "body": [{"op": "acquire", "var": "buf", "line": 10},
                  {"op": "overspan", "var": "buf", "line": 12},
                  {"op": "release", "var": "buf", "line": 14}]}]})
    if [(x.code, x.line, x.kind) for x in osp] != [("OWN025", 12, "pooled buffer")]:
        fails.append(f"an `overspan` fact should raise OWN025 at the view line (12) "
                     f"tagged a pooled buffer, got "
                     f"{[(x.code, x.line, x.kind) for x in osp]}")
    checks += 1
    # P-015: the OWN025 slice runs Rent site -> view site (the primary anchor is the VIEW
    # at line 12, but the flow's first hop is the Rent at line 10) — the pooled-buffer
    # branch's own flow path, distinct from the OWN002 case above.
    if not osp or osp[0].flow != (
            ("Framer.cs", 10, "rented 'buf' here"),
            ("Framer.cs", 12, "viewed here at full length, past what it was rented for")):
        fails.append(f"OWN025 Rent->view reachability flow wrong: "
                     f"{osp[0].flow if osp else None!r}")

    # POOL005, view STORED INTO A FIELD (P-007 / issue #198). A full-length view of a
    # pooled FIELD assigned into another field (`_view = _buf.AsMemory()`, read only
    # elsewhere) is caught at the STORE: the extractor's field pass fires on the view
    # EXPRESSION regardless of where the result is stored, so it emits the SAME
    # pool-tagged acquire/overspan/release flow the inline field over-read does. This
    # pins that fact shape — the frozen target the extractor is validated against —
    # exactly as `dotnet run … --flow-locals` emits it (acquire carries `kind:"pool"`).
    checks += 1
    vif = check_facts({"module": "M", "functions": [
        {"name": "FieldViewFramer.Capture", "file": "Framer.cs",
         "body": [{"op": "acquire", "var": "_buf", "line": 13, "kind": "pool"},
                  {"op": "overspan", "var": "_buf", "line": 14},
                  {"op": "release", "var": "_buf", "line": 14}]}]})
    if [(x.code, x.line, x.kind) for x in vif] != [("OWN025", 14, "pooled buffer")]:
        fails.append(f"POOL005 view-into-field: a pool-tagged acquire/overspan/release "
                     f"flow should raise OWN025 at the store/view line (14) tagged a "
                     f"pooled buffer, got {[(x.code, x.line, x.kind) for x in vif]}")

    # --- output surfaces (Уровень 1): the same finding renders for a human, a
    #     GitHub annotation, and an MSBuild/VS Error List line. The format lives
    #     in the core (one checker), so the Action/script stay thin wrappers.
    fnd = Finding(file="src/A.cs", line=42, code="OWN001", component="A",
                  event="bus.X", handler="OnX", message="event 'bus.X' leaks (leak)",
                  kind="subscription token")
    checks += 1
    gh = render_finding(fnd, "github")
    if not gh.startswith("::error file=src/A.cs,line=42,title=OWN001::"):
        fails.append(f"github render wrong prefix: {gh!r}")
    if "leaks (leak) [resource: subscription token]" not in gh:
        fails.append(f"github render missing message/tag: {gh!r}")
    checks += 1
    mb = render_finding(fnd, "msbuild")
    if mb != ("src/A.cs(42): error OWN001: event 'bus.X' leaks (leak) "
              "[resource: subscription token]"):
        fails.append(f"msbuild render wrong: {mb!r}")
    checks += 1
    # an unknown format falls back to the human line (no crash).
    if render_finding(fnd, "bogus") != fnd.render():
        fails.append("unknown format should fall back to human render")
    checks += 1
    # GitHub command metacharacters in a path/message are escaped, never raw.
    nasty = Finding(file="a,b:c.cs", line=1, code="OWN001", component="C",
                    event="e", handler="h", message="line1\nline2 50% off",
                    kind="timer")
    g2 = render_finding(nasty, "github")
    if "a%2Cb%3Ac.cs" not in g2 or "%0A" not in g2 or "50%25 off" not in g2:
        fails.append(f"github render did not escape metacharacters: {g2!r}")

    # --severity is a presentation choice: warning renders ::warning / : warning:
    # / warning:, error (default) is unchanged.
    checks += 1
    if not render_finding(fnd, "github", "warning").startswith(
            "::warning file=src/A.cs,line=42,"):
        fails.append("github render did not honor severity=warning")
    checks += 1
    if "src/A.cs(42): warning OWN001:" not in render_finding(fnd, "msbuild", "warning"):
        fails.append("msbuild render did not honor severity=warning")
    checks += 1
    if "src/A.cs:42: warning: [OWN001]" not in render_finding(fnd, "human", "warning"):
        fails.append("human render did not honor severity=warning")
    checks += 1
    # the default stays error (no accidental severity drift).
    if not render_finding(fnd, "msbuild").startswith("src/A.cs(42): error OWN001:"):
        fails.append("msbuild default severity should remain error")

    # --- SARIF 2.1.0 export (build_sarif) ------------------------------------
    canon = check_facts(facts)  # the canonical one-leak CustomerViewModel fixture
    sf = build_sarif(canon)
    checks += 1
    if sf.get("version") != "2.1.0" or "$schema" not in sf or len(sf["runs"]) != 1:
        fails.append(f"SARIF envelope wrong: version={sf.get('version')!r}")
    driver = sf["runs"][0]["tool"]["driver"]
    checks += 1
    if driver.get("name") != "Own.NET":
        fails.append(f"SARIF tool.driver.name wrong: {driver.get('name')!r}")
    checks += 1
    if [(r["id"], r["shortDescription"]["text"]) for r in driver["rules"]] != \
            [("OWN001", TITLES["OWN001"])]:
        fails.append(f"SARIF rules catalogue wrong: {driver['rules']}")
    checks += 1
    if len(sf["runs"][0]["results"]) != len(canon):
        fails.append(f"SARIF results {len(sf['runs'][0]['results'])} != "
                     f"findings {len(canon)}")
    else:
        res0 = sf["runs"][0]["results"][0]
        pl = res0["locations"][0]["physicalLocation"]
        checks += 1
        if (res0["ruleId"], res0["level"], pl["artifactLocation"]["uri"],
                pl["region"]["startLine"]) != \
                ("OWN001", "error", "CustomerViewModel.cs", 12):
            fails.append(f"SARIF result0 wrong: {res0['ruleId']} {res0['level']} "
                         f"{pl['artifactLocation']['uri']}:{pl['region']['startLine']}")
        checks += 1
        if "[resource: subscription token]" not in res0["message"]["text"]:
            fails.append("SARIF result0 message lost the resource tag")
        checks += 1
        if res0["properties"].get("resourceKind") != "subscription token" or \
                res0["properties"].get("event") != "bus.CustomerChanged":
            fails.append(f"SARIF result0 properties wrong: {res0['properties']}")

    # level mapping: advisory -> note, intrinsic-warning -> warning, else error;
    # a --severity warning host downgrades a hard leak (advisory stays a note).
    _adv = Finding(file="A.cs", line=3, code="OWN050", component="", event="",
                   handler="", message="skip", kind="subscription token", advisory=True)
    _wrn = Finding(file="A.cs", line=4, code="OWN001", component="C", event="e",
                   handler="h", message="leak", kind="subscription token",
                   severity="warning")
    _err = Finding(file="A.cs", line=5, code="OWN001", component="C", event="e",
                   handler="h", message="leak", kind="subscription token")
    checks += 1
    if [r["level"] for r in build_sarif([_adv, _wrn, _err])["runs"][0]["results"]] != \
            ["note", "warning", "error"]:
        fails.append("SARIF level mapping (advisory/warning/error) wrong")
    checks += 1
    if [r["level"] for r in build_sarif([_adv, _err], "warning")["runs"][0]["results"]] != \
            ["note", "warning"]:
        fails.append("SARIF --severity warning should downgrade a hard leak")
    # empty findings -> a valid, empty SARIF run (no crash, no bogus rules).
    checks += 1
    empty = build_sarif([])
    if empty["runs"][0]["results"] or empty["runs"][0]["tool"]["driver"]["rules"]:
        fails.append("SARIF empty run should have no results/rules")

    # the thesis: own-check SARIF is read by the oracle's EXISTING SARIF parser and
    # classified as a leak — own joins the cross-tool diff with no bespoke text parser.
    checks += 1
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import oracle_compare as _oc
    rt = _oc.parse_sarif(json.dumps(build_sarif(canon)), "own", [])
    if [(p.path, p.line, p.rule, p.cls) for p in rt] != \
            [("CustomerViewModel.cs", 12, "OWN001", "leak")]:
        fails.append("SARIF oracle round-trip wrong: "
                     f"{[(p.path, p.line, p.rule, p.cls) for p in rt]}")

    for f in fails:
        print(f"OWNIR FAIL: {f}")
    print(f"ownir: {checks - len(fails)}/{checks} bridge checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
