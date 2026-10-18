#!/usr/bin/env python3
"""Derive data/r1/index.tsv and data/r2/index.tsv from the search results (all.tsv).

Excluded: the two target repos, every repo+path of the #412 development sample, duplicate repo+path,
and (round 2 only) every repo+path of round 1. Order is kept from all.tsv.
Usage: python scripts/make_index.py <dev-sample-index.tsv> [--check]
  --check compares with the committed index files instead of writing them (exit 1 on a difference).
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
TARGETS = {"meziantou/Meziantou.Framework", "dotnet/maui"}


def read(path: str) -> list[tuple[str, ...]]:
    with open(path, encoding="utf-8") as f:
        return [tuple(line.rstrip("\n").split("\t")) for line in f if line.strip()]


def derive(all_tsv: str, excluded: set[tuple[str, str]]) -> list[tuple[str, ...]]:
    out: list[tuple[str, ...]] = []
    seen: set[tuple[str, str]] = set()
    for repo, path, sha in read(all_tsv):
        key = (repo, path)
        if repo in TARGETS or key in excluded or key in seen:
            continue
        seen.add(key)
        out.append((repo, path, sha))
    return out


def main() -> int:
    dev = {(r[0], r[1]) for r in read(sys.argv[1])}
    check = "--check" in sys.argv
    r1 = derive(os.path.join(ROOT, "data", "r1", "all.tsv"), dev)
    r2 = derive(os.path.join(ROOT, "data", "r2", "all.tsv"), dev | {(r, p) for r, p, _ in r1})
    status = 0
    for name, rows in (("r1", r1), ("r2", r2)):
        target = os.path.join(ROOT, "data", name, "index.tsv")
        text = "".join("\t".join(r) + "\n" for r in rows)
        if check:
            with open(target, encoding="utf-8", newline="") as f:
                same = f.read() == text
            repos = len({r[0] for r in rows})
            print(f"{name}: {len(rows)} files, {repos} repos, matches committed: {same}")
            status |= 0 if same else 1
        else:
            with open(target, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            print(f"{name}: {len(rows)} files written")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
