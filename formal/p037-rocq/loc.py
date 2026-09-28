#!/usr/bin/env python3
"""LOC counter: model vs proof lines, and lines added relative to a reference
directory of the same file names (diff -u), code only.

code  = non-blank lines outside (* comments *)
proof = code lines from `Proof` through `Qed.`/`Defined.` (inclusive)
model = code - proof
added = lines added relative to the file of the same name in REF_DIR, code only
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
    ref_dir, this_dir = Path(sys.argv[1]), Path(sys.argv[2])
    names = sys.argv[3:]
    tot = {"ref": [0, 0], "this": [0, 0], "added": 0}
    cols = ["REF model", "REF proof", "THIS model", "THIS proof", "THIS added"]
    print(f"{'file':<20}" + "".join(f"{c:>11}" for c in cols))
    for n in names:
        ref = code_lines((ref_dir / n).read_text()) if (ref_dir / n).exists() else []
        this = code_lines((this_dir / n).read_text()) if (this_dir / n).exists() else []
        rm, rp = split(ref)
        tm, tp = split(this)
        added = sum(1 for d in difflib.ndiff(ref, this) if d.startswith("+ "))
        tot["ref"][0] += rm
        tot["ref"][1] += rp
        tot["this"][0] += tm
        tot["this"][1] += tp
        tot["added"] += added
        print(f"{n:<20}{rm:>11}{rp:>11}{tm:>11}{tp:>11}{added:>11}")
    refs, this_s = sum(tot["ref"]), sum(tot["this"])
    print(f"{'TOTAL':<20}{tot['ref'][0]:>11}{tot['ref'][1]:>11}{tot['this'][0]:>11}"
          f"{tot['this'][1]:>11}{tot['added']:>11}")
    if refs:
        print(f"model+proof: REF {refs}, THIS {this_s}, delta {this_s - refs:+d} "
              f"({100 * (this_s - refs) / refs:+.1f}%)")


if __name__ == "__main__":
    main()
