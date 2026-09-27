#!/usr/bin/env python3
"""Same LOC counter for both sides of the control (MathComp #367 vs plain Rocq).

code  = non-blank lines outside (* comments *)
proof = code lines from `Proof` through `Qed.`/`Defined.` (inclusive)
model = code - proof
added = lines added relative to the MathComp file of the same name (diff -u), code only
"""

import difflib
import re
import sys
from pathlib import Path


def code_lines(text: str) -> list[str]:
    text = re.sub(r"\(\*.*?\*\)", "", text, flags=re.S)
    return [ln.rstrip() for ln in text.splitlines() if ln.strip()]


def split(lines: list[str]) -> tuple[int, int]:
    proof, inproof = 0, False
    for ln in lines:
        if re.match(r"\s*Proof\b", ln) or re.search(r"\bProof\.", ln):
            inproof = True
        if inproof:
            proof += 1
        if re.search(r"\b(Qed|Defined|Abort)\.", ln):
            inproof = False
    return len(lines) - proof, proof


def main() -> None:
    mc_dir, plain_dir = Path(sys.argv[1]), Path(sys.argv[2])
    names = sys.argv[3:]
    tot = {"mc": [0, 0], "plain": [0, 0], "added": 0}
    print(f"{'file':<20}{'MC model':>9}{'MC proof':>9}{'PL model':>9}{'PL proof':>9}{'PL added':>9}")
    for n in names:
        mc = code_lines((mc_dir / n).read_text()) if (mc_dir / n).exists() else []
        pl = code_lines((plain_dir / n).read_text()) if (plain_dir / n).exists() else []
        mm, mp = split(mc)
        pm, pp = split(pl)
        added = sum(1 for d in difflib.ndiff(mc, pl) if d.startswith("+ "))
        tot["mc"][0] += mm
        tot["mc"][1] += mp
        tot["plain"][0] += pm
        tot["plain"][1] += pp
        tot["added"] += added
        print(f"{n:<20}{mm:>9}{mp:>9}{pm:>9}{pp:>9}{added:>9}")
    mcs, pls = sum(tot["mc"]), sum(tot["plain"])
    print(f"{'TOTAL':<20}{tot['mc'][0]:>9}{tot['mc'][1]:>9}{tot['plain'][0]:>9}"
          f"{tot['plain'][1]:>9}{tot['added']:>9}")
    if mcs:
        print(f"model+proof: MathComp {mcs}, plain {pls}, delta {pls - mcs:+d} "
              f"({100 * (pls - mcs) / mcs:+.1f}%)")


if __name__ == "__main__":
    main()
