#!/usr/bin/env python3
"""
Zero-dependency regression suite for the OwnLang PoC.

Run:  python tests/run_tests.py
Each case lists the diagnostic codes it expects (order-independent). A case
passes iff the produced set of error codes equals the expected set.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.parser import parse, ParseError          # noqa: E402
from ownlang.lexer import LexError                     # noqa: E402
from ownlang.cfg import build_cfg, collect_signatures  # noqa: E402
from ownlang.analysis import analyze                    # noqa: E402
from ownlang.diagnostics import Severity                # noqa: E402
from ownlang.codegen import generate                    # noqa: E402

PRELUDE = (
    "module M\n"
    "resource Buffer { acquire rent release give }\n"
    "resource Conn { acquire open release close }\n"
    "extern fn Fill(borrow_mut Buffer);\n"
    "extern fn Hash(borrow Buffer);\n"
    "extern fn Store(consume Buffer);\n"
)


def codes(src: str) -> list[str]:
    try:
        mod = parse(src)
    except (ParseError, LexError):
        return ["OWN020"]
    rnames = {r.name for r in mod.resources}
    sigs = collect_signatures(mod)
    cs: list[str] = []
    for fn in mod.functions:
        cfg, d1 = build_cfg(fn, rnames, sigs)
        d2 = analyze(cfg)
        cs += [d.code for d in (d1 + d2) if d.severity == Severity.ERROR]
    return cs


# (name, source-after-prelude, expected error codes)
CASES = [
    # ---- clean programs ----
    ("ok_basic", "fn f(){ let b = acquire Buffer(10); release b; }", []),
    ("ok_move", "fn f(){ let a = acquire Buffer(1); let c = move a; release c; }", []),
    ("ok_borrows",
     "fn f(){ let b = acquire Buffer(1); borrow b as s { use s; } "
     "borrow_mut b as m { use m; } release b; }", []),
    ("ok_both_branches",
     "fn f(){ let b = acquire Buffer(1); if (c) { release b; } else { release b; } }", []),
    ("ok_return_owned",
     "fn f() -> Buffer { let b = acquire Buffer(1); return b; }", []),
    ("ok_borrowed_param_use",
     "fn f(x: &Buffer) { use x; }", []),
    ("ok_shared_read_while_shared",
     "fn f(){ let b = acquire Buffer(1); borrow b as s { use b; } release b; }", []),
    ("ok_nested_release_both_arms",
     "fn f(){ let b = acquire Buffer(1); if (c) { use b; release b; } "
     "else { use b; release b; } }", []),
    # ---- clean programs exercising extern calls ----
    ("ok_extern_borrow_calls",
     "fn f(){ let b = acquire Buffer(1); Fill(b); Hash(b); release b; }", []),
    ("ok_extern_consume",
     "fn f(){ let b = acquire Buffer(1); Store(b); }", []),
    ("ok_call_in_borrow_block",
     "fn f(){ let b = acquire Buffer(1); borrow_mut b as m { Fill(m); } "
     "borrow b as r { Hash(r); } release b; }", []),

    # ---- single faults: linear ----
    ("leak", "fn f(){ let b = acquire Buffer(10); }", ["OWN001"]),
    ("leak_one_branch",
     "fn f(){ let b = acquire Buffer(1); if (c) { release b; } }", ["OWN001"]),
    ("double_release",
     "fn f(){ let b = acquire Buffer(1); release b; release b; }", ["OWN003"]),
    ("use_after_release",
     "fn f(){ let b = acquire Buffer(1); release b; use b; }", ["OWN002"]),
    ("use_after_move",
     "fn f(){ let a = acquire Buffer(1); let c = move a; use a; release c; }",
     ["OWN005"]),
    ("double_move",
     "fn f(){ let a = acquire Buffer(1); let b = move a; let c = move a; "
     "release b; release c; }", ["OWN005"]),
    ("return_borrow",
     "fn f(x: &Buffer) -> Buffer { return x; }", ["OWN004"]),

    # ---- single faults: loan / permission conflicts (now distinct codes) ----
    ("mut_while_shared",
     "fn f(){ let b = acquire Buffer(1); borrow b as s { borrow_mut b as m "
     "{ use m; } } release b; }", ["OWN006"]),
    ("move_while_borrowed",
     "fn f(){ let b = acquire Buffer(1); borrow b as s { let c = move b; "
     "release c; } }", ["OWN007"]),
    ("release_while_borrowed",
     "fn f(){ let b = acquire Buffer(1); borrow b as s { release b; } }",
     ["OWN008"]),
    ("double_mut",
     "fn f(){ let b = acquire Buffer(1); borrow_mut b as m1 { borrow_mut b as "
     "m2 { use m2; } } release b; }", ["OWN011"]),
    ("shared_while_mut",
     "fn f(){ let b = acquire Buffer(1); borrow_mut b as m { borrow b as s "
     "{ use s; } } release b; }", ["OWN012"]),
    ("use_owner_while_mut",
     "fn f(){ let b = acquire Buffer(1); borrow_mut b as m { use b; } release b; }",
     ["OWN013"]),

    # ---- single faults: join / "maybe" ----
    ("use_after_maybe_release",
     "fn f(){ let b = acquire Buffer(1); if (c) { release b; } use b; }",
     ["OWN001", "OWN009"]),
    ("use_after_maybe_move",
     "fn f(){ let b = acquire Buffer(1); if (c) { let d = move b; release d; } "
     "use b; }", ["OWN001", "OWN010"]),

    # ---- structural / resolution (renumbered) ----
    ("release_non_owned",
     "fn f(x: &Buffer) { release x; }", ["OWN034"]),
    ("move_non_owned",
     "fn f(x: &Buffer) { let y = move x; }", ["OWN034"]),
    ("borrow_non_owned",
     "fn f(n: int) { borrow n as s { use s; } }", ["OWN034"]),
    ("undefined", "fn f(){ use ghost; }", ["OWN030"]),
    ("undefined_resource", "fn f(){ let x = acquire Nope(1); release x; }", ["OWN030"]),
    ("copy_owned",
     "fn f(){ let a = acquire Buffer(1); let b = a; release a; }", ["OWN032"]),
    ("missing_return",
     "fn f() -> Buffer { let b = acquire Buffer(1); release b; }", ["OWN033"]),
    ("loop_rejected", "fn f(){ while (x) { use x; } }", ["OWN020"]),
    ("async_rejected", "fn f(){ async { use x; } }", ["OWN020"]),

    # ---- extern boundary ----
    ("unknown_call",
     "fn f(){ let b = acquire Buffer(1); Mystery(b); release b; }", ["OWN040"]),
    ("arg_shared_where_mut",
     "fn f(){ let b = acquire Buffer(1); borrow b as r { Fill(r); } release b; }",
     ["OWN041"]),
    ("arg_arity",
     "fn f(){ let b = acquire Buffer(1); Fill(b, b); release b; }", ["OWN041"]),
    ("arg_plain_to_resource",
     "fn f(n: int){ Hash(n); }", ["OWN041"]),
    ("consume_then_use",
     "fn f(){ let b = acquire Buffer(1); Store(b); use b; }", ["OWN002"]),
    ("consume_while_borrowed",
     "fn f(){ let b = acquire Buffer(1); borrow b as r { Store(b); } }", ["OWN007"]),

    # ---- multiple faults in one function ----
    ("leak_and_uafr",
     "fn f(){ let a = acquire Buffer(1); let b = acquire Buffer(2); "
     "release b; use b; }", ["OWN001", "OWN002"]),
]


# Golden codegen smoke: a real ArrayPool-backed buffer must (a) check clean and
# (b) lower to genuine .NET — Rent/Return, try/finally, a Span view — with NO
# runtime "released?" flag (the release is hoisted out of the try, so it needs
# no guard).
GOLDEN = (
    "module PoolDemo\n"
    "resource Buffer {\n"
    "  acquire rent\n"
    "  release give\n"
    '  emit_type    "byte[]"\n'
    '  emit_acquire "ArrayPool<byte>.Shared.Rent({args})"\n'
    '  emit_release "ArrayPool<byte>.Shared.Return({0})"\n'
    '  emit_borrow  "{0}.AsSpan()"\n'
    "}\n"
    "extern fn Fill(borrow_mut Buffer);\n"
    "extern fn Hash(borrow Buffer);\n"
    "fn process(size: int) {\n"
    "  let buf = acquire Buffer(size);\n"
    "  borrow_mut buf as bytes { Fill(bytes); }\n"
    "  borrow buf as view { Hash(view); }\n"
    "  release buf;\n"
    "}\n"
)


def golden_smoke() -> list[str]:
    """Returns a list of failure strings (empty == pass)."""
    fails: list[str] = []
    cs = codes(GOLDEN)
    errs = [c for c in cs if c.startswith("OWN")]
    if errs:
        fails.append(f"golden should check clean, got {sorted(set(errs))}")
    cs_out = generate(parse(GOLDEN))
    must_contain = [
        "ArrayPool<byte>.Shared.Rent(size)",
        "ArrayPool<byte>.Shared.Return(buf)",
        "byte[] buf =",
        "buf.AsSpan()",
        "try",
        "finally",
        "Fill(bytes)",
        "Hash(view)",
    ]
    for s in must_contain:
        if s not in cs_out:
            fails.append(f"golden C# missing: {s!r}")
    # the Return must be inside finally and NOT also inside the try body
    body = cs_out
    if body.count("ArrayPool<byte>.Shared.Return(buf)") != 1:
        fails.append("golden C# should Return exactly once (hoisted into finally)")
    return fails


def run() -> int:
    passed = 0
    failed = 0
    for name, body, expected in CASES:
        got = sorted(set(codes(PRELUDE + body)))
        want = sorted(set(expected))
        if got == want:
            passed += 1
        else:
            failed += 1
            print(f"FAIL {name}")
            print(f"     expected {want}")
            print(f"     got      {got}")

    # codegen smoke: every clean case must generate without throwing
    cg_total = len([c for c in CASES if not c[2]])
    cg_fail = 0
    for name, body, expected in CASES:
        if expected:
            continue
        try:
            generate(parse(PRELUDE + body))
        except Exception as e:  # noqa: BLE001
            cg_fail += 1
            print(f"CODEGEN FAIL {name}: {type(e).__name__}: {e}")

    golden_fails = golden_smoke()
    for f in golden_fails:
        print(f"GOLDEN FAIL: {f}")

    total = passed + failed
    print(f"\nanalysis: {passed}/{total} passed, {failed} failed")
    print(f"codegen:  {cg_total - cg_fail}/{cg_total} generated cleanly")
    print(f"golden:   {'PASS' if not golden_fails else 'FAIL'}")
    return 1 if (failed or cg_fail or golden_fails) else 0


if __name__ == "__main__":
    raise SystemExit(run())
