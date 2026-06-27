#!/usr/bin/env python3
"""Reactive-effect stability tests — EFF001, the effect storm (P-020).

Two layers, both with no dotnet/JS dependency:
  1. the pure core analysis (ownlang/effects.py): the identity-stability lattice,
     reference propagation, cycle safety, and the IO + unstable -> storm rule;
  2. the OwnIR bridge (ownlang/ownir.py): the optional `effects` block routes
     through check_facts to an EFF001 Finding at the effect's call site, and the
     code reaches the SARIF rules catalogue.

Run:  python tests/test_effects.py
      python tests/run_tests.py     (runs it as part of the suite)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.effects import (
    STABLE,
    UNKNOWN,
    UNSTABLE,
    Binding,
    Effect,
    _Lattice,
    find_effect_storms,
)
from ownlang.ownir import build_sarif, check_facts


def _stab(binds: list[Binding]) -> dict[str, str]:
    lat = _Lattice(binds)
    return {b.name: lat.stability(b.name) for b in binds}


def run() -> int:
    fails: list[str] = []
    checks = 0

    def check(cond: bool, msg: str) -> None:
        nonlocal checks
        checks += 1
        if not cond:
            fails.append(msg)

    # ---- the stability lattice ----
    check(_stab([Binding("f", "object", (), 1)]) == {"f": UNSTABLE}, "object literal is UNSTABLE")
    check(_stab([Binding("f", "array", (), 1)]) == {"f": UNSTABLE}, "array literal is UNSTABLE")
    check(_stab([Binding("f", "new", (), 1)]) == {"f": UNSTABLE}, "new expr must be UNSTABLE")
    for stable_kind in ("memo", "callback", "ref", "prop", "primitive", "import", "fn"):
        check(_stab([Binding("f", stable_kind, (), 1)]) == {"f": STABLE},
              f"{stable_kind} must be STABLE")
    check(_stab([Binding("f", "call", (), 1)]) == {"f": UNKNOWN}, "opaque call must be UNKNOWN")

    # propagation: alias of an unstable literal is unstable; alias of a memo is stable.
    check(_stab([Binding("a", "object", (), 1), Binding("c", "ident", ("a",), 2)])
          == {"a": UNSTABLE, "c": UNSTABLE}, "instability must propagate through an alias")
    check(_stab([Binding("m", "memo", (), 1), Binding("d", "ident", ("m",), 2)])
          == {"m": STABLE, "d": STABLE}, "alias of a memo stays STABLE")
    # join is worst-case: derive from a stable AND an unstable ref -> unstable.
    check(_stab([Binding("s", "memo", (), 1), Binding("u", "object", (), 2),
                 Binding("d", "derive", ("s", "u"), 3)])["d"] == UNSTABLE,
          "a derivation is as unstable as its worst input")
    # identity cycle must not hang and stays conservative.
    check(_stab([Binding("a", "ident", ("b",), 1), Binding("b", "ident", ("a",), 2)])
          == {"a": UNKNOWN, "b": UNKNOWN}, "an identity cycle must resolve to UNKNOWN")

    # ---- the storm rule ----
    fire = find_effect_storms([
        Effect("D", ("filters",), True, (Binding("filters", "object", (), 32),), "D.tsx", 33)])
    check(len(fire) == 1 and fire[0].dep == "filters" and fire[0].decl_line == 32,
          "IO + unstable dep must fire one EFF001 anchored at the effect line")
    check("request storm" in fire[0].message and "object literal" in fire[0].message,
          "the message must name the storm and the unstable kind")

    silent_cases = [
        ("no IO", Effect("D", ("f",), False, (Binding("f", "object", (), 1),), "D.tsx", 2)),
        ("memo dep", Effect("D", ("f",), True, (Binding("f", "memo", (), 1),), "D.tsx", 2)),
        ("opaque call", Effect("D", ("f",), True, (Binding("f", "call", (), 1),), "D.tsx", 2)),
        ("primitive dep", Effect("D", ("n",), True, (Binding("n", "primitive", (), 1),), "f", 2)),
        ("dep with no binding (prop)", Effect("D", ("tenantId",), True, (), "D.tsx", 2)),
    ]
    for label, e in silent_cases:
        check(find_effect_storms([e]) == [], f"{label} must stay silent (no false positive)")

    # derivation finding names the upstream origin and the path.
    derived = find_effect_storms([
        Effect("D", ("c",), True,
               (Binding("a", "object", (), 1), Binding("c", "ident", ("a",), 2)), "D.tsx", 3)])[0]
    check(derived.origin == "a" and derived.path == ("c", "a"),
          "a derived storm must point at the upstream unstable origin")
    check("derives from 'a'" in derived.message, "the message must explain the derivation")

    # ---- the OwnIR bridge ----
    facts = {
        "ownir_version": 0, "module": "D", "components": [],
        "effects": [
            {"component": "Dashboard", "file": "Dashboard.tsx", "line": 33, "io": True,
             "deps": ["filters"],
             "bindings": [{"name": "filters", "init": "object", "refs": [], "line": 32}]},
            {"component": "Dashboard", "file": "Dashboard.tsx", "line": 40, "io": True,
             "deps": ["stable"],
             "bindings": [{"name": "stable", "init": "memo", "refs": ["x"], "line": 39}]},
        ],
    }
    findings = check_facts(facts)
    eff = [f for f in findings if f.code == "EFF001"]
    check(len(eff) == 1, f"bridge must yield one EFF001 (memo silent), got {len(eff)}")
    check(eff[0].file == "Dashboard.tsx" and eff[0].line == 33,
          "EFF001 must anchor at the effect call site")
    check(bool(eff[0].flow), "EFF001 must carry a reachability slice (effect -> fix site)")

    # the code reaches the SARIF rules catalogue with its title.
    rules = {r["id"]: r["shortDescription"]["text"] for r in
             build_sarif(eff)["runs"][0]["tool"]["driver"]["rules"]}
    check("EFF001" in rules and "storm" in rules["EFF001"], "EFF001 must appear in the SARIF rules")

    # malformed effects degrade gracefully (additive/optional, never a crash).
    check(check_facts({"ownir_version": 0, "components": [], "effects": "nope"}) == [],
          "a malformed effects block must not crash check_facts")

    for f in fails:
        print(f"EFFECTS FAIL: {f}")
    print(f"effects: {checks - len(fails)}/{checks} EFF001 stability checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
