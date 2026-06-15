#!/usr/bin/env python3
"""
WPF lifetime corpus, as a self-checking test (slice #1 of the `lifetimes` work).

Each corpus/wpf/<case>/ folder holds a real WPF lifetime bug pattern reduced to
OwnLang: before.cs (buggy) / after.cs (fixed) / case.own (a faithful OwnLang
reduction, with a `kind`-tagged resource) / expected-diagnostics.txt (the codes
the checker must produce) / notes.md (the pattern, source, and honesty caveat).

The point of slice #1 is that the *core ownership checker already catches the
main class of WPF leaks* (a subscription/timer that is never disposed = OWN001;
touched after dispose = OWN002), and that the domain-neutral resource-kind tag
reaches the rendered output as `[resource: <kind>]`. So this test asserts BOTH:

  * the produced error codes match expected-diagnostics.txt, and
  * the rendered diagnostic carries the `[resource: ...]` metadata.

If the checker ever stops catching one of these patterns, or the kind metadata
stops flowing to the output, the suite goes red.

NOTE: case.own is a hand reduction, not C# the checker ingested -- OwnLang has no
C# front-end (a later slice). The corpus shows the ownership *logic* maps onto
real WPF bugs, not that the tool scanned real C#.

Run:  python tests/test_wpf.py
      python tests/run_tests.py     (runs it as part of the suite)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.analysis import analyze
from ownlang.buffers import validate_policies
from ownlang.cfg import (
    build_cfg,
    collect_kinds,
    collect_policies,
    collect_signatures,
)
from ownlang.diagnostics import Severity
from ownlang.lexer import LexError
from ownlang.lifetimes import check_lifetimes
from ownlang.parser import ParseError, parse

_CORPUS = os.path.join(os.path.dirname(__file__), "..", "corpus", "wpf")


def _check(src: str) -> tuple[list[str], str]:
    """(error codes, rendered-pretty text) the checker produces for one source."""
    try:
        mod = parse(src)
    except (ParseError, LexError):
        return ["OWN020"], ""
    rnames = {r.name for r in mod.resources}
    sigs = collect_signatures(mod)
    kinds = collect_kinds(mod)
    diags = list(validate_policies(collect_policies(mod)))
    diags += check_lifetimes(mod)
    for fn in mod.functions:
        cfg, d1 = build_cfg(fn, rnames, sigs, None, kinds)
        diags += d1 + analyze(cfg)
    errors = [d for d in diags if d.severity == Severity.ERROR]
    codes = [d.code for d in errors]
    rendered = "\n".join(d.render_pretty("case.own", src) for d in errors)
    return codes, rendered


def _cases() -> list[str]:
    if not os.path.isdir(_CORPUS):
        return []
    return sorted(d for d in os.listdir(_CORPUS)
                  if os.path.isdir(os.path.join(_CORPUS, d)))


def run() -> int:
    """Check every WPF case against expected codes + kind metadata; return 0/1."""
    fails: list[str] = []
    rows: list[tuple[str, str]] = []
    checked = 0
    matched = 0
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
        checked += 1
        with open(exp, encoding="utf-8") as f:
            want = sorted(w for w in f.read().split() if w)
        with open(own, encoding="utf-8") as f:
            source = f.read()
        codes, rendered = _check(source)
        got = sorted(codes)   # keep multiplicity: a duplicate code is a regression
        ok = True
        if got != want:
            fails.append(f"{case}: expected {want}, got {got}")
            ok = False
        # a case that tags a resource kind must surface it as [resource: ...];
        # region-escape cases (no kinded resource) are exempt.
        if 'kind "' in source and "[resource: " not in rendered:
            fails.append(f"{case}: rendered output carries no [resource: ...] tag")
            ok = False
        if ok:
            matched += 1
        rows.append((case, ",".join(want)))

    print("WPF lifetime corpus (corpus/wpf/):")
    width = max((len(c) for c, _ in rows), default=0)
    for case, codes in rows:
        print(f"  {case:<{width}}  {codes}")
    for f in fails:
        print(f"WPF FAIL: {f}")
    print(f"wpf: {matched}/{checked} cases match expected codes + carry kind metadata")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
