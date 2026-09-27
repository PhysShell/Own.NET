#!/usr/bin/env python3
"""Hard LOC gate for the election reuse gate (research/plain-rocq-election-instance).

Counts handwritten .v CODE lines (non-blank, outside comments) that are new or
changed relative to the frozen base 1bfd5ed (#369 head): every line of new
.v files, plus lines added/changed in existing .v files (RustTables.v is
generated and excluded). Exits 1 above 180. Run it throughout the work.
"""

import difflib
import re
import subprocess
import sys
from pathlib import Path

BASE = "1bfd5ed16c5c6f1ffa257b4091770d1dedd7778c"
LIMIT = 180
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def code(text: str) -> list[str]:
    text = re.sub(r"\(\*.*?\*\)", "", text, flags=re.S)
    return [ln.rstrip() for ln in text.splitlines() if ln.strip()]


def at_base(rel: str) -> str | None:
    r = subprocess.run(["git", "show", f"{BASE}:{rel}"], cwd=REPO,
                       capture_output=True, text=True, check=False)
    return r.stdout if r.returncode == 0 else None


def main() -> int:
    total = 0
    for f in sorted((HERE / "theories").glob("*.v")):
        if f.name == "RustTables.v":
            continue
        rel = str(f.relative_to(REPO))
        now = code(f.read_text())
        old = at_base(rel)
        if old is None:
            n = len(now)
            kind = "new"
        else:
            n = sum(1 for d in difflib.ndiff(code(old), now) if d.startswith("+ "))
            kind = "changed"
        if n:
            print(f"  {f.name:<18} {kind:<8} {n:>4}")
        total += n
    verdict = "OK" if total <= LIMIT else "OVER BUDGET -> STOP: KILL GENERIC REUSE"
    print(f"  total new/changed .v code lines: {total} / {LIMIT}  {verdict}")
    return 0 if total <= LIMIT else 1


if __name__ == "__main__":
    sys.exit(main())
