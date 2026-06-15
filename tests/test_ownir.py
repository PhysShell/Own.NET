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

from ownlang.ownir import OWNIR_VERSION, OwnIRError, check_facts, load, to_own
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
        if (d0.file, d0.line, d0.code) != ("DisposableFieldViewModel.cs", 11, "OWN001"):
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

    for f in fails:
        print(f"OWNIR FAIL: {f}")
    print(f"ownir: {checks - len(fails)}/{checks} bridge checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
