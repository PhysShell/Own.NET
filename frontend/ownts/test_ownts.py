#!/usr/bin/env python3
"""Pins the OwnTS spike end-to-end through the real core:
  - Dashboard.tsx  -> three OWN001 leaks (timer/subscribe/listener) + one EFF001
                      effect storm (unstable object dep + IO);
  - DashboardClean.tsx -> silent (cleanups + useMemo'd dep);
  - EffectStorm.tsx -> exactly two EFF001 (direct object dep + its derived alias),
                      every memo/ref/call/primitive/no-IO case staying silent.
EFF001 here is a real core verdict (ownlang/effects.py), not a frontend heuristic.
Zero deps. Run: python frontend/ownts/test_ownts.py"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", ".."))

import ownts  # noqa: E402

from ownlang.ownir import check_facts  # noqa: E402


def codes(tsx: str) -> list[str]:
    path = os.path.join(HERE, "examples", tsx)
    facts = ownts.to_ownir(ownts.extract(path), tsx, ownts.extract_effects(path))
    return [f.code for f in check_facts(facts)]


def main() -> int:
    leaky = codes("Dashboard.tsx")
    assert leaky == ["OWN001", "OWN001", "OWN001", "EFF001"], f"leaky -> {leaky}"

    clean = codes("DashboardClean.tsx")
    assert clean == [], f"clean should be silent -> {clean}"

    # resource-kind mapping is preserved through the bridge
    comps = ownts.extract(os.path.join(HERE, "examples", "Dashboard.tsx"))
    kinds = sorted(r.resource for c in comps for r in c.resources)
    assert kinds == ["subscribe", "subscription", "timer"], kinds

    # EFF001 is a real core verdict: the showcase fires on exactly the direct
    # object dep and its derived alias; memo/ref/opaque-call/primitive/no-IO are
    # all silent (the core's conservative, low-false-positive stability analysis).
    storm = codes("EffectStorm.tsx")
    assert storm == ["EFF001", "EFF001"], f"EffectStorm -> {storm}"

    print("OwnTS spike OK: leaky=3xOWN001+EFF001, clean=0, kinds=timer/subscribe/"
          "subscription, EffectStorm=2xEFF001 (core stability analysis, propagation "
          "+ conservative).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
