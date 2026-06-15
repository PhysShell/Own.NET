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

from ownlang.ownir import check_facts, to_own
from ownlang.parser import parse

_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "ownir",
                        "sample.facts.json")


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

    for f in fails:
        print(f"OWNIR FAIL: {f}")
    print(f"ownir: {checks - len(fails)}/{checks} bridge checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
