"""N3 pilot G1: is a buggy-tree warning's call or capture line changed or removed by the fix?

usage: python -I g1_touched.py <root with src/<slug>/{base,fix} and <run>/<slug>/{base,fix}> [run]
"""

import difflib
import os
import sys


def rows(root: str, run: str, slug: str, side: str) -> list[list[str]]:
    p = os.path.join(root, run, slug, side, "warnings.tsv")
    return [r.split("\t") for r in open(p, encoding="utf-8").read().splitlines()[1:]]


def lines(path: str) -> list[str]:
    if not os.path.exists(path):
        return []
    return open(path, encoding="utf-8", errors="replace").read().splitlines()


def main() -> int:
    root = sys.argv[1]
    run = sys.argv[2] if len(sys.argv) > 2 else "run"
    for slug in sorted(os.listdir(os.path.join(root, run))):
        for c in rows(root, run, slug, "base"):
            f, line, cap = c[0], int(c[1]), int(c[8])
            a = lines(os.path.join(root, "src", slug, "base", f))
            b = lines(os.path.join(root, "src", slug, "fix", f))
            touched: set[int] = set()
            ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
            for op, i1, i2, _j1, _j2 in ops:
                if op in ("replace", "delete"):
                    touched.update(range(i1 + 1, i2 + 1))
            call = "TOUCHED" if line in touched else "untouched"
            capture = "TOUCHED" if cap in touched else "untouched"
            text = a[cap - 1].strip()[:70]
            site = f"{slug}\t{f}:{line}\tcapture {cap}"
            print(f"{site}\tcall={call}\tcapture={capture}\t{c[4]}x{c[5]}\t{text}")
        for c in rows(root, run, slug, "fix"):
            print(f"   fix-warning\t{slug}\t{c[0]}:{c[1]}\t{c[4]}x{c[5]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
