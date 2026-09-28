#!/usr/bin/env python3
"""P-037 PCS-0 falsifiers F0-F2 (docs/notes/p037-pcs0-producer-canonical-shadow.md §D).

Not a test_*.py: it needs the built extractor and own-guarded-report.
Run:  python tests/p037_pcs0_falsifiers.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import p037_pcs0 as pcs


def main() -> int:
    run = pcs.extract(pcs.ROOT, ["docs/evidence/p037-pcs0-probes/Transitive.cs"])
    act, can = ({s["method"].split(".")[-1]: s["legacy"] for s in run[k]["summary"]}
                for k in ("actual", "shadow"))
    body = {f["name"].split(".")[-1]: f["body"] for f in run["shadow_facts"]["functions"]}
    top, pas = ([(o["op"], o.get("callee", "").split(".")[-1]) for o in body[m]]
                for m in ("Top", "Pass"))
    checks = {
        f"F0  A->B->C: A_actual={act['Top']} B_actual={act['Outer']} B_shadow={can['Outer']} "
        f"A_shadow={can['Top']}, A's shadow ops {top}":
            (act["Top"], act["Outer"], can["Outer"], can["Top"], top)
            == ("must", "must", "may", "may", [("call", "Outer")]),
        f"F1  borrow chain: Pass actual={act['Pass']} shadow={can['Pass']}, shadow ops {pas}":
            (act["Pass"], can["Pass"], pas) == ("no", "no", [("call", "Peek")]),
        "F2  -o is byte-identical with and without the flag": run["o_identical"],
    }
    for label, ok in checks.items():
        print(f"{'ok ' if ok else 'MISS'} {label}")
    missed = sum(not ok for ok in checks.values())
    print(f"RESULT: {'all falsifiers pass' if not missed else f'{missed} falsifier(s) missed'}")
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
