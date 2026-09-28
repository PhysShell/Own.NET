#!/usr/bin/env python3
"""Negative controls of the election reuse gate: every mutant must be REJECTED.

Copies theories/ to a temp dir, applies one mutation to Election.v, and
re-checks Lfp.v + Election.v. Exits 1 if any mutant still checks.
"""

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
WARN = ["-w", "-notation-for-abbreviation"]

MUTANTS = [
    ("E1", "broken flat join: One g + One h = One g even for g <> h",
     "  | One g, One h => if geqb g h then One g else Conflict",
     "  | One g, One h => One g"),
    ("E2", "non-monotone import: Conflict imports as ENone",
     "  | x, _ => x\n  end.",
     "  | ENone, _ => ENone\n  | Conflict, _ => ENone\n  end."),
    ("E3", "wrong binding: One h imports as One caller whether or not h = callee",
     "  | One h, (BId c g | BNeg c g) => if geqb h c then One g else ENone",
     "  | One h, (BId c g | BNeg c g) => One g"),
    ("E4", "chaotic theorem without the fairness hypothesis",
     "Theorem k10e_chaotic sched : (forall i, In i sched) ->",
     "Theorem k10e_chaotic sched : (forall i, In i sched \\/ True) ->"),
]


def check(d: Path) -> str | None:
    for f in ("Lfp", "Election"):
        r = subprocess.run(["rocq", "compile", *WARN, "-Q", "theories", "PlainSpike",
                            f"theories/{f}.v"], cwd=d, capture_output=True, text=True,
                           check=False)
        if r.returncode:
            out = r.stdout + r.stderr
            m = re.search(r'line (\d+)', out)
            line = int(m.group(1)) if m else 0
            src = (d / f"theories/{f}.v").read_text().splitlines()
            stmt = next((s for s in reversed(src[:line])
                         if re.match(r"(Lemma|Theorem|Definition)\b", s)), "?")
            return f"{f}.v:{line} [{stmt.split(':')[0].strip()}]"
    return None


def main() -> int:
    survivors = []
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        shutil.copytree(HERE / "theories", d / "theories",
                        ignore=shutil.ignore_patterns("*.vo*", "*.glob", ".*.aux"))
        target = d / "theories/Election.v"
        pristine = target.read_text()
        print(f"baseline: {'OK' if check(d) is None else 'FAILED'}")
        for mid, what, old, new in MUTANTS:
            if pristine.count(old) != 1:
                print(f"{mid}: mutation site not found exactly once")
                return 2
            target.write_text(pristine.replace(old, new))
            res = check(d)
            verdict = "KILLED  " if res else "SURVIVED"
            print(f"{mid} {verdict} {what}\n      -> {res or 'still checks'}")
            if res is None:
                survivors.append(mid)
        target.write_text(pristine)
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
