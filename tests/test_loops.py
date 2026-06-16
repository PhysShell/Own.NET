#!/usr/bin/env python3
"""
Loop support (P-016 A1): the core analyses `while` via a worklist fixpoint over
the back-edge, instead of skipping it as OWN020.

The point of these cases is the *cross-iteration* facts a single topological pass
cannot see: a resource released inside the loop is, on the second turn, released
again (OWN003) and used after release (OWN009); a resource acquired each turn and
not released leaks (OWN001). Balanced acquire/release — and a borrow that opens
and closes within the body — stay clean (no false positive). Each case pins the
exact set of error codes, so the fixpoint can't silently regress to the old
loop-free behavior.

Run:  python tests/test_loops.py
      python tests/run_tests.py     (runs it as part of the suite)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.analysis import analyze
from ownlang.cfg import build_cfg, collect_signatures
from ownlang.diagnostics import Severity
from ownlang.lexer import LexError
from ownlang.parser import ParseError, parse

_PRELUDE = (
    "module Loops\n"
    "resource Conn { acquire open release close }\n"
)


def _codes(body: str) -> set[str]:
    """The set of error codes the checker produces for one function body (the
    Conn prelude is prepended). A parse/lex rejection surfaces as OWN020, matching
    the driver."""
    try:
        mod = parse(_PRELUDE + body)
    except (ParseError, LexError):
        return {"OWN020"}
    rnames = {r.name for r in mod.resources}
    sigs = collect_signatures(mod)
    out: set[str] = set()
    for fn in mod.functions:
        cfg, d1 = build_cfg(fn, rnames, sigs)
        d2 = analyze(cfg)
        out |= {d.code for d in (d1 + d2) if d.severity == Severity.ERROR}
    return out


# (name, body, expected error-code set, note)
CASES: list[tuple[str, str, set[str], str]] = [
    ("clean_balanced",
     "fn f(n: int){ while (n) { let c = acquire Conn(1); release c; } }",
     set(), "acquire+release each turn is balanced"),
    ("clean_use_in_loop_release_after",
     "fn f(n: int){ let c = acquire Conn(1); while (n) { use c; } release c; }",
     set(), "used across iterations, released once after the loop"),
    ("clean_borrow_in_loop",
     "fn f(n: int){ let c = acquire Conn(1); "
     "while (n) { borrow c as r { use r; } } release c; }",
     set(), "a borrow opens and closes within the body -> loans match at the back-edge"),
    ("clean_nested_balanced",
     "fn f(n: int){ while (n) { while (n) { let c = acquire Conn(1); release c; } } }",
     set(), "nested loops converge; inner acquire/release balanced"),
    ("leak_each_iter",
     "fn f(n: int){ while (n) { let c = acquire Conn(1); use c; } }",
     {"OWN001"}, "acquired each turn, never released -> leak"),
    ("leak_nested",
     "fn f(n: int){ while (n) { while (n) { let c = acquire Conn(1); use c; } } }",
     {"OWN001"}, "leak inside a nested loop still surfaces"),
    ("xiter_double_release",
     "fn f(n: int){ let c = acquire Conn(1); while (n) { release c; } }",
     {"OWN001", "OWN003"},
     "2nd turn double-releases (OWN003, fixpoint-only); 0-trip path leaks (OWN001)"),
    ("xiter_use_after_release",
     "fn f(n: int){ let c = acquire Conn(1); while (n) { use c; release c; } }",
     {"OWN001", "OWN003", "OWN009"},
     "2nd turn uses c after last turn released it (OWN009, fixpoint-only)"),
]


def run() -> int:
    fails: list[str] = []
    checks = 0

    for name, body, want, _note in CASES:
        checks += 1
        got = _codes(body)
        if got != want:
            fails.append(f"{name}: expected {sorted(want)}, got {sorted(got)}")
        # loops must never be reported as unsupported any more.
        checks += 1
        if "OWN020" in got:
            fails.append(f"{name}: a `while` loop was wrongly rejected as OWN020")

    # the fixpoint's headline wins: cross-iteration faults a single pass misses.
    checks += 1
    if "OWN003" not in _codes(
            "fn f(n: int){ let c = acquire Conn(1); while (n) { release c; } }"):
        fails.append("cross-iteration double-release (OWN003) was not detected")
    checks += 1
    if "OWN009" not in _codes(
            "fn f(n: int){ let c = acquire Conn(1); while (n) { use c; release c; } }"):
        fails.append("cross-iteration use-after-release (OWN009) was not detected")

    # regression guard: the reject path still works for the constructs that ARE
    # out of scope (async/for/loop) -> OWN020, so graduating `while` didn't open
    # the gate for everything.
    checks += 1
    if _codes("fn f(){ async { use x; } }") != {"OWN020"}:
        fails.append("async should still be rejected as OWN020")
    checks += 1
    if _codes("fn f(){ for (n) { use x; } }") != {"OWN020"}:
        fails.append("for-loops should still be rejected as OWN020")

    for f in fails:
        print(f"LOOPS FAIL: {f}")
    print(f"loops: {checks - len(fails)}/{checks} loop (while) cases pass")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
