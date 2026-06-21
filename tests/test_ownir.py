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
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tempfile

from ownlang.diagnostics import TITLES
from ownlang.ownir import (
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
        Service("Cache", "singleton", ("Conn",)),  # -> transient disposable: DI003
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
    # regression (CodeRabbit review): a param ONLY forwarded to another call is
    # ambiguous without that callee's contract, so it is NOT inferred (stays plain)
    # -- the v1 boundary. The forwarding fn and its caller stay silent (no false
    # positive, no crash); transitive inference is the follow-up that resolves it.
    checks += 1
    amb = check_facts({"module": "M", "functions": [
        {"name": "forward", "file": "F.cs", "params": [{"name": "s", "line": 1}],
         "body": [{"op": "call", "callee": "sink", "args": ["s"], "line": 2}]},
        {"name": "sink", "file": "F.cs",
         "params": [{"name": "x", "effect": "consume", "line": 5}],
         "body": [{"op": "release", "var": "x", "line": 6}]},
        {"name": "caller", "file": "F.cs",
         "body": [{"op": "acquire", "var": "s", "line": 10},
                  {"op": "call", "callee": "forward", "args": ["s"], "line": 11},
                  {"op": "release", "var": "s", "line": 12}]}]})
    if amb:
        fails.append(f"an ambiguous pass-through param must not be inferred, crash, "
                     f"or false-positive, got {[(x.component, x.code) for x in amb]}")

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
