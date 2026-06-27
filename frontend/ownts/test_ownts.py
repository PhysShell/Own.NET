#!/usr/bin/env python3
"""Pins the OwnTS spike: the leaky fixture drops exactly three OWN001 leaks through
the core, the clean fixture drops none, and the EFF001 heuristic fires only on the
unstable-dependency effect. Zero deps. Run: python frontend/ownts/test_ownts.py"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", ".."))

import ownts  # noqa: E402

from ownlang.ownir import check_facts  # noqa: E402


def codes(tsx: str) -> list[str]:
    comps = ownts.extract(os.path.join(HERE, "examples", tsx))
    return [f.code for f in check_facts(ownts.to_ownir(comps, tsx))]


def main() -> int:
    leaky = codes("Dashboard.tsx")
    assert leaky == ["OWN001", "OWN001", "OWN001"], f"leaky -> {leaky}"

    clean = codes("DashboardClean.tsx")
    assert clean == [], f"clean should be silent -> {clean}"

    # resource-kind mapping is preserved through the bridge
    comps = ownts.extract(os.path.join(HERE, "examples", "Dashboard.tsx"))
    kinds = sorted(r.resource for c in comps for r in c.resources)
    assert kinds == ["subscribe", "subscription", "timer"], kinds

    # EFF001 is a frontend-only heuristic (not core-verified): fires on the leaky
    # unstable-dep effect, silent on the useMemo'd clean one.
    assert ownts._eff001_notes(os.path.join(HERE, "examples", "Dashboard.tsx"))
    assert not ownts._eff001_notes(os.path.join(HERE, "examples", "DashboardClean.tsx"))

    print("OwnTS spike OK: leaky=3xOWN001, clean=0, kinds=timer/subscribe/subscription, "
          "EFF001 heuristic fires only on the unstable dep.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
