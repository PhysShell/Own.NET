#!/usr/bin/env python3
"""
Real-world corpus, as a self-checking test.

Each corpus/real-world/<case>/ folder holds a real ArrayPool/ownership bug
pattern: before.cs (buggy) / after.cs (fixed) / case.own (a faithful OwnLang
reduction of it) / expected-diagnostics.txt (the codes the checker must produce
on case.own) / notes.md (the pattern, the source, and the honesty caveat).

This module runs every case.own and asserts its diagnostics match the
expected-diagnostics.txt next to it, so the corpus stays honest: if the checker
ever stops catching one of these real patterns, the suite goes red.

NOTE: case.own is a hand reduction of the C# pattern, not C# the checker
ingested -- OwnLang has no C# front-end. The corpus shows the ownership *logic*
maps onto real bugs, not that the tool scanned real C#.

Run:  python tests/test_corpus.py
      python tests/run_tests.py     (runs it as part of the suite)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.parser import parse, ParseError                # noqa: E402
from ownlang.lexer import LexError                           # noqa: E402
from ownlang.cfg import build_cfg, collect_signatures, collect_policies  # noqa: E402
from ownlang.analysis import analyze                          # noqa: E402
from ownlang.buffers import validate_policies                 # noqa: E402
from ownlang.diagnostics import Severity                      # noqa: E402

_CORPUS = os.path.join(os.path.dirname(__file__), "..", "corpus", "real-world")


def _codes(src: str) -> list[str]:
    try:
        mod = parse(src)
    except (ParseError, LexError):
        return ["OWN020"]
    rnames = {r.name for r in mod.resources}
    sigs = collect_signatures(mod)
    out = [d.code for d in validate_policies(collect_policies(mod))
           if d.severity == Severity.ERROR]
    for fn in mod.functions:
        cfg, d1 = build_cfg(fn, rnames, sigs)
        out += [d.code for d in (d1 + analyze(cfg)) if d.severity == Severity.ERROR]
    return out


def _cases() -> list[str]:
    if not os.path.isdir(_CORPUS):
        return []
    return sorted(d for d in os.listdir(_CORPUS)
                  if os.path.isdir(os.path.join(_CORPUS, d)))


def run() -> int:
    fails: list[str] = []
    rows: list[tuple[str, str]] = []
    for case in _cases():
        d = os.path.join(_CORPUS, case)
        own = os.path.join(d, "case.own")
        exp = os.path.join(d, "expected-diagnostics.txt")
        for required in (own, exp, os.path.join(d, "before.cs"),
                         os.path.join(d, "after.cs"), os.path.join(d, "notes.md")):
            if not os.path.exists(required):
                fails.append(f"{case}: missing {os.path.basename(required)}")
        if not (os.path.exists(own) and os.path.exists(exp)):
            continue
        want = sorted(w for w in open(exp, encoding="utf-8").read().split() if w)
        got = sorted(set(_codes(open(own, encoding="utf-8").read())))
        if got != want:
            fails.append(f"{case}: expected {want}, got {got}")
        rows.append((case, ",".join(want)))

    print("real-world corpus (corpus/real-world/):")
    width = max((len(c) for c, _ in rows), default=0)
    for case, codes in rows:
        print(f"  {case:<{width}}  {codes}")
    for f in fails:
        print(f"CORPUS FAIL: {f}")
    print(f"corpus: {len(rows) - len(fails)}/{len(_cases())} cases match "
          f"their expected diagnostics")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
