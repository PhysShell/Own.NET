#!/usr/bin/env python3
"""
Spec conformance pilot (spec/OwnCore.md, spec/Lifetimes.md).

One canonical program per normative rule, asserting that the rule's diagnostic
fires. This is the seam that keeps the written spec and the checker from
drifting: if a rule stops firing on its example, the build goes red.

Membership, not exact-set: each case asserts the rule's code is *among* the
produced codes (a minimal program that isolates exactly one code is often
awkward; firing is what conformance needs). The broader suites
(test_gallery / test_lifetimes / test_wpf / run_tests CASES) pin exact behaviour.

Run:  python tests/test_spec.py
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
from ownlang.lexer import LexError
from ownlang.lifetimes import check_lifetimes
from ownlang.parser import ParseError, parse

_BUF = "resource Buf { acquire rent release give }"


def _codes(src: str) -> list[str]:
    """All error codes the full checker produces for one source string."""
    try:
        mod = parse(src)
    except (ParseError, LexError):
        return ["PARSE_ERROR"]
    rnames = {r.name for r in mod.resources}
    sigs = collect_signatures(mod)
    kinds = collect_kinds(mod)
    out = [d.code for d in validate_policies(collect_policies(mod))]
    out += [d.code for d in check_lifetimes(mod)]
    for fn in mod.functions:
        cfg, d1 = build_cfg(fn, rnames, sigs, None, kinds)
        out += [d.code for d in (d1 + analyze(cfg))]
    return out


# (rule id, code that must fire, program)
CASES: list[tuple[str, str, str]] = [
    ("OwnCore-R1", "OWN001",
     f"module M\n{_BUF}\nfn f() {{ let a = acquire Buf(); }}"),
    ("OwnCore-R2", "OWN002",
     f"module M\n{_BUF}\nfn f() {{ let a = acquire Buf(); release a; use a; }}"),
    ("OwnCore-R3", "OWN003",
     f"module M\n{_BUF}\nfn f() {{ let a = acquire Buf(); release a; release a; }}"),
    ("OwnCore-R4", "OWN005",
     f"module M\n{_BUF}\n"
     "fn f() { let a = acquire Buf(); let b = move a; use a; release b; }"),
    ("OwnCore-R5", "OWN007",
     f"module M\n{_BUF}\n"
     "fn f() { let a = acquire Buf(); borrow a as x { let b = move a; release b; } }"),
    ("OwnCore-R6", "OWN008",
     f"module M\n{_BUF}\n"
     "fn f() { let a = acquire Buf(); borrow a as x { release a; } }"),
    ("OwnCore-R7", "OWN013",
     f"module M\n{_BUF}\n"
     "fn f() { let a = acquire Buf(); borrow_mut a as x { use a; } release a; }"),
    ("OwnCore-R8", "OWN006",
     f"module M\n{_BUF}\n"
     "fn f() { let a = acquire Buf(); borrow a as x { borrow_mut a as y { } } "
     "release a; }"),
    ("OwnCore-R9", "OWN012",
     f"module M\n{_BUF}\n"
     "fn f() { let a = acquire Buf(); borrow_mut a as x { borrow a as y { } } "
     "release a; }"),
    ("OwnCore-R11", "OWN032",
     f"module M\n{_BUF}\n"
     "fn f() { let a = acquire Buf(); let b = a; release a; }"),
    ("OwnCore-R12", "OWN034",
     f"module M\n{_BUF}\nfn f(x: int) {{ release x; }}"),
    ("OwnCore-S8", "OWN040",
     f"module M\n{_BUF}\nfn f() {{ let a = acquire Buf(); Unknown(a); release a; }}"),
    ("Lifetimes-L1", "OWN036",
     "module M\nlifetime A < B;\nlifetime B < A;"),
    ("Lifetimes-L2", "OWN030",
     "module M\nlifetime App;\nfn f() lifetime Bogus { }"),
    ("Lifetimes-L3", "OWN014",
     "module M\nlifetime App;\nlifetime ViewModel < App;\n"
     "fn VM(bus: EventBus lifetime App) lifetime ViewModel { subscribe self to bus; }"),
    # buffers
    ("Buffer-B1", "OWN015",
     "module M\nfn f() -> Buffer { let b = Buffer.stack(16); return b; }"),
    ("Buffer-B4", "OWN018",
     "module M\nfn f(flag: bool) { let b = Buffer.stack(flag); }"),
    ("Buffer-B8", "OWN030",
     "module M\npolicy P { bogus = 1; }"),
    ("Buffer-B9", "OWN025",
     f"module M\n{_BUF}\n"
     "fn f() { let b = acquire Buf(); overspan b; release b; }"),
    # structural
    ("Struct-OWN031", "OWN031",
     f"module M\n{_BUF}\n"
     "fn f() { let a = acquire Buf(); let a = acquire Buf(); release a; }"),
    ("Struct-OWN033", "OWN033",
     f"module M\n{_BUF}\nfn f() -> Buf {{ }}"),
    ("Struct-OWN035", "OWN035",
     f"module M\n{_BUF}\nfn f(n: int) -> Buf {{ return n; }}"),
    ("Struct-OWN041", "OWN041",
     f"module M\n{_BUF}\nextern fn Need(consume Buf);\nfn f(x: int) {{ Need(x); }}"),
]


def run() -> int:
    """Check every spec rule fires on its canonical example; return 0/1."""
    fails: list[str] = []
    matched = 0
    for rule, code, src in CASES:
        got = _codes(src)
        if code in got:
            matched += 1
        else:
            fails.append(f"{rule}: expected {code} to fire, got {sorted(set(got))}")
    for f in fails:
        print(f"SPEC FAIL: {f}")
    print(f"spec: {matched}/{len(CASES)} normative rules fire on their example")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
