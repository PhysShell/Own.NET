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

from ownlang.ownir import (
    OWNIR_VERSION,
    Finding,
    OwnIRError,
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
_DI_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures",
                           "ownir", "di.facts.json")


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

    for f in fails:
        print(f"OWNIR FAIL: {f}")
    print(f"ownir: {checks - len(fails)}/{checks} bridge checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
