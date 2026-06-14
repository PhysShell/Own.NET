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

from ownlang.analysis import analyze
from ownlang.buffers import validate_policies
from ownlang.cfg import build_cfg, collect_policies, collect_signatures
from ownlang.codegen import generate
from ownlang.diagnostics import Severity
from ownlang.lexer import LexError
from ownlang.parser import ParseError, parse
from ownlang.report import build_report

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
    pols = collect_policies(mod)
    cs: list[str] = [d.code for d in validate_policies(pols)
                     if d.severity == Severity.ERROR]
    for fn in mod.functions:
        cfg, d1 = build_cfg(fn, rnames, sigs, pols)
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
    ("return_plain_as_resource",
     "fn f(n: int) -> Buffer { return n; }", ["OWN035"]),
    ("return_empty_as_resource",
     "fn f() -> Buffer { return; }", ["OWN035"]),
    ("return_value_from_void",
     "fn g(n: int){ return n; }", ["OWN035"]),
    ("return_wrong_resource_type",
     "fn f() -> Buffer { let c = acquire Conn(1); return c; }", ["OWN035"]),
    ("return_wrong_resource_param",
     "fn f(c: Conn) -> Buffer { return c; }", ["OWN035"]),
    ("ok_return_owned_conn",
     "fn f() -> Conn { let c = acquire Conn(1); return c; }", []),
    ("ok_bare_return_void",
     "fn f(){ let b = acquire Buffer(1); release b; return; }", []),
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

    # ---- ownership/borrow soundness (adversarial) ----
    # Clean programs that must NOT be rejected (false-positive guard).
    ("ok_sequential_mut_borrows",
     "fn f(){ let b = acquire Buffer(1); borrow_mut b as m1 { use m1; } "
     "borrow_mut b as m2 { use m2; } release b; }", []),
    ("ok_consume_both_arms",
     "fn f(){ let b = acquire Buffer(1); if (c) { Store(b); } "
     "else { Store(b); } }", []),
    ("ok_move_chain",
     "fn f(){ let a = acquire Buffer(1); let b = move a; let c = move b; "
     "release c; }", []),
    ("ok_temp_borrows_then_consume",
     "fn f(){ let b = acquire Buffer(1); Hash(b); Fill(b); Store(b); }", []),
    ("ok_nested_shared_borrows",
     "fn f(){ let b = acquire Buffer(1); borrow b as s { borrow b as t "
     "{ use t; } } release b; }", []),
    # Bad programs that must be rejected (false-negative guard).
    ("borrow_moved_name",
     "fn f(){ let a = acquire Buffer(1); let c = move a; borrow a as s "
     "{ use s; } release c; }", ["OWN005"]),
    ("release_moved_name",
     "fn f(){ let a = acquire Buffer(1); let c = move a; release a; "
     "release c; }", ["OWN005"]),
    ("void_return_in_borrow_leaks",
     "fn f(){ let b = acquire Buffer(1); borrow b as s { use s; return; } }",
     ["OWN001"]),
    ("double_consume",
     "fn f(){ let b = acquire Buffer(1); Store(b); Store(b); }", ["OWN002"]),
    ("consume_borrow_binding",
     "fn f(){ let b = acquire Buffer(1); borrow b as s { Store(s); } "
     "release b; }", ["OWN034"]),
    ("mut_call_under_shared",
     "fn f(){ let b = acquire Buffer(1); borrow b as s { Fill(b); } "
     "release b; }", ["OWN006"]),
    ("leak_inner_acquire_in_borrow",
     "fn f(){ let a = acquire Buffer(1); borrow a as s { let b = acquire "
     "Buffer(2); use s; } release a; }", ["OWN001"]),
    ("move_borrow_binding",
     "fn f(){ let b = acquire Buffer(1); borrow b as s { let c = move s; "
     "release c; } release b; }", ["OWN034"]),
    ("shadow_borrow_binding",
     "fn f(){ let b = acquire Buffer(1); borrow b as s { borrow b as s "
     "{ use s; } } release b; }", ["OWN031"]),
    ("return_moved_and_leak",
     "fn f() -> Buffer { let a = acquire Buffer(1); let b = move a; "
     "return a; }", ["OWN001", "OWN005"]),
    ("plain_copy_to_resource_param",
     "fn f(){ let a = acquire Buffer(1); let b = a; Hash(b); release a; }",
     ["OWN032", "OWN041"]),

    # ---- buffer storage policies: clean ----
    ("buf_scratch_ok",
     "fn f(n: int){ let b = Buffer.scratch(n, inline = 1024); "
     "borrow_mut b as m { Fill(m); } release b; }", []),
    ("buf_stack_const_ok",
     "fn f(){ let b = Buffer.stack(256); borrow_mut b as m { Fill(m); } "
     "release b; }", []),
    ("buf_stack_dyn_bounded_ok",
     "fn f(n: int){ let b = Buffer.stack(n, max = 1024); release b; }", []),
    ("buf_inline_ok",
     "fn f(){ let b = Buffer.inline(64); release b; }", []),
    ("buf_pooled_local_ok",
     "fn f(n: int){ let b = Buffer.pooled(n); borrow_mut b as m { Fill(m); } "
     "release b; }", []),
    ("buf_branchy_release_ok",
     "fn f(n: int){ let b = Buffer.pooled(n); if (c) { release b; } "
     "else { release b; } }", []),
    ("buf_overlapping_fifo_ok",
     "fn f(n: int){ let a = Buffer.pooled(n); let b = Buffer.pooled(n); "
     "release a; release b; }", []),
    ("buf_overlapping_lifo_ok",
     "fn f(n: int){ let a = Buffer.pooled(n); let b = Buffer.pooled(n); "
     "release b; release a; }", []),
    ("buf_scratch_bad_fallback",
     "fn f(n: int){ let b = Buffer.scratch(n, fallback = forbiden); "
     "release b; }", ["OWN030"]),
    ("buf_scratch_nonident_fallback",
     "fn f(n: int){ let b = Buffer.scratch(n, fallback = 0); release b; }",
     ["OWN030"]),
    ("buf_move_release_ok",
     "fn f(n: int){ let a = Buffer.pooled(n); let b = move a; release b; }", []),
    ("buf_bad_namespace",
     "fn f(n: int){ let b = Foo.stack(n, max = 1024); release b; }", ["OWN030"]),
    ("buf_move_escapes",
     "fn f(n: int) -> Buffer { let a = Buffer.stack(n, max = 100); "
     "let b = move a; return b; }", ["OWN015"]),
    ("buf_sibling_move_ok",
     "fn f(n: int){ let a = Buffer.pooled(n); if (c) { let b = move a; "
     "release b; } else { release a; } }", []),
    ("buf_disjoint_sequential_ok",
     "fn f(n: int){ let a = Buffer.pooled(n); release a; "
     "let b = Buffer.pooled(n); release b; }", []),
    ("buf_bad_policy_ref",
     "fn f(n: int){ let b = Buffer.scratch(n, policy = 0); release b; }",
     ["OWN030"]),
    ("buf_bad_inline_bound",
     "fn f(n: int){ let b = Buffer.scratch(n, inline = bogus); release b; }",
     ["OWN030"]),
    ("buf_bad_max_bound",
     "fn f(n: int){ let b = Buffer.stack(n, max = bogus); release b; }",
     ["OWN030"]),
    ("buf_unknown_option",
     "fn f(n: int){ let b = Buffer.scratch(n, fallbak = forbidden); "
     "release b; }", ["OWN030"]),
    ("buf_unknown_policy_setting",
     "policy P { fallbak = forbidden; } "
     "fn f(n: int){ let b = Buffer.scratch(n, policy = P); release b; }",
     ["OWN030"]),
    ("buf_size_not_int_bool",
     "fn f(flag: bool){ let b = Buffer.pooled(flag); release b; }", ["OWN018"]),
    ("buf_size_not_int_owned",
     "fn f(){ let r = acquire Conn(1); let b = Buffer.pooled(r); "
     "release b; release r; }", ["OWN018"]),
    ("buf_inline_dynamic_rejected",
     "fn f(n: int){ let b = Buffer.inline(n, max = 1024); release b; }",
     ["OWN021"]),
    ("buf_size_borrow_temp",
     "fn f(x: &Buffer){ let n = x; let b = Buffer.pooled(n); release b; }",
     ["OWN018"]),
    ("buf_local_after_release_ok",
     "fn f(n: int){ let b = Buffer.pooled(n); let x = 1; release b; "
     "let y = x; }", []),
    ("buf_inline_literal_ok",
     "fn f(){ let b = Buffer.inline(256); release b; }", []),
    ("buf_policy_bad_clear",
     "policy Sensitive { clear_on_release = ture; } "
     "fn f(n: int){ let b = Buffer.scratch(n, policy = Sensitive); release b; }",
     ["OWN030"]),
    ("buf_bad_counters",
     "fn f(n: int){ let b = Buffer.scratch(n, counters = ture); release b; }",
     ["OWN030"]),
    ("buf_bad_trace",
     "fn f(n: int){ let b = Buffer.scratch(n, trace = ture); release b; }",
     ["OWN030"]),
    ("buf_policy_bools_ok",
     "policy S { clear_on_release = true; counters = false; trace = off; } "
     "fn f(n: int){ let b = Buffer.scratch(n, policy = S); release b; }", []),
    ("buf_duplicate_option",
     "fn f(n: int){ let b = Buffer.scratch(n, fallback = forbidden, "
     "fallback = pool); release b; }", ["OWN030"]),
    ("buf_duplicate_policy_setting",
     "policy P { inline_bytes = 512; inline_bytes = 1024; } "
     "fn f(n: int){ let b = Buffer.scratch(n, policy = P); release b; }",
     ["OWN030"]),
    ("buf_inline_override_ignores_bad_policy",
     "policy P { inline_bytes = bogus; } "
     "fn f(n: int){ let b = Buffer.scratch(n, policy = P, inline = 128); "
     "release b; }", []),
    ("buf_bad_policy_inline_no_override",
     "policy P { inline_bytes = bogus; } "
     "fn f(n: int){ let b = Buffer.scratch(n, policy = P); release b; }",
     ["OWN030"]),
    ("buf_alias_redecl_ok",
     "fn f(n: int){ let a = Buffer.pooled(n); if (c) { let b = move a; "
     "release b; } else { release a; } let b = acquire Conn(); release b; }",
     []),
    ("res_partial_overlap_ok",
     "fn f(){ let a = acquire Buffer(1); let c = acquire Conn(1); "
     "release a; use c; release c; }", []),
    ("buf_nested_release_ok",
     "fn f(n: int){ let a = acquire Conn(1); let b = Buffer.pooled(n); "
     "borrow a as s { release b; } release a; }", []),
    ("buf_local_helper_ok",
     "fn helper(x: &mut Buffer){ use x; } "
     "fn f(n: int){ let b = Buffer.pooled(n); helper(b); release b; }", []),
    ("buf_native_ok",
     "fn f(n: int){ let b = Buffer.native(n); release b; }", []),
    ("buf_policy_ok",
     "policy P { inline_bytes = 512; fallback = pool; } "
     "fn f(n: int){ let b = Buffer.scratch(n, policy = P); release b; }", []),
    ("buf_sensitive_cleared_ok",
     "fn f(n: int){ let b = Buffer.pooled(n, sensitive = true, clear = true); "
     "release b; }", []),
    ("buf_sensitive_policy_ok",
     "policy Secret { sensitive = true; clear_on_release = true; } "
     "fn f(n: int){ let b = Buffer.scratch(n, policy = Secret); release b; }", []),

    # ---- buffer storage policies: faults ----
    ("buf_sensitive_no_clear",
     "fn f(n: int){ let b = Buffer.pooled(n, sensitive = true); release b; }",
     ["OWN024"]),
    ("buf_sensitive_policy_no_clear",
     "policy Secret { sensitive = true; clear_on_release = false; } "
     "fn f(n: int){ let b = Buffer.scratch(n, policy = Secret); release b; }",
     ["OWN024"]),
    ("buf_bad_sensitive",
     "fn f(n: int){ let b = Buffer.scratch(n, sensitive = ture); release b; }",
     ["OWN030"]),
    ("buf_stack_dyn_unbounded",
     "fn f(n: int){ let b = Buffer.stack(n); release b; }", ["OWN021"]),
    ("buf_stack_too_large",
     "fn f(){ let b = Buffer.stack(1000000); release b; }", ["OWN019"]),
    ("buf_scratch_escapes_return",
     "fn f(n: int) -> Buffer { let b = Buffer.scratch(n); return b; }",
     ["OWN015"]),
    ("buf_stack_escapes_return",
     "fn f() -> Buffer { let b = Buffer.stack(64); return b; }", ["OWN015"]),
    ("buf_scratch_escapes_consume",
     "fn f(n: int){ let b = Buffer.scratch(n); Store(b); }", ["OWN016"]),
    ("buf_pooled_escapes_return",
     "fn f(n: int) -> Buffer { let b = Buffer.pooled(n); return b; }",
     ["OWN017"]),
    ("buf_pooled_escapes_consume",
     "fn f(n: int){ let b = Buffer.pooled(n); Store(b); }", ["OWN017"]),
    ("buf_native_escapes_return",
     "fn f(n: int) -> Buffer { let b = Buffer.native(n); return b; }",
     ["OWN017"]),
    ("buf_scratch_forbid_dynamic",
     "fn f(n: int){ let b = Buffer.scratch(n, fallback = forbidden); "
     "release b; }", ["OWN023"]),
    ("buf_scratch_leak",
     "fn f(n: int){ let b = Buffer.scratch(n); }", ["OWN001"]),
    ("buf_unknown_mode",
     "fn f(n: int){ let b = Buffer.bogus(n); release b; }", ["OWN030"]),
    ("buf_release_while_borrowed",
     "fn f(n: int){ let b = Buffer.scratch(n); borrow b as s { release b; } }",
     ["OWN008"]),
    ("buf_moved_then_used",
     "fn f(n: int){ let a = Buffer.pooled(n); let b = move a; use a; "
     "release b; }", ["OWN005"]),
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


BUFFER_GOLDEN = (
    "module ScratchDemo\n"
    "policy DefaultScratch { inline_bytes = 1024; fallback = pool; "
    "trace = debug; counters = true; clear_on_release = false; }\n"
    "extern fn Fill(borrow_mut Buffer);\n"
    "extern fn Hash(borrow Buffer);\n"
    "fn parse(size: int) {\n"
    "  let tmp = Buffer.scratch(size, inline = 1024, fallback = pool);\n"
    "  borrow_mut tmp as bytes { Fill(bytes); }\n"
    "  borrow tmp as view { Hash(view); }\n"
    "  release tmp;\n"
    "}\n"
)


def buffer_smoke() -> list[str]:
    """A scratch buffer must check clean, lower to the stack-first/pool-fallback
    pattern with the trace + counter hooks, ship the [Conditional] runtime
    support, and produce a compile-time report that names the chosen backends."""
    fails: list[str] = []
    cs = [c for c in codes(BUFFER_GOLDEN) if c.startswith("OWN")]
    if cs:
        fails.append(f"buffer golden should check clean, got {sorted(set(cs))}")
    out = generate(parse(BUFFER_GOLDEN))
    must_contain = [
        "Span<byte> tmp_backing = stackalloc byte[1024];",
        "if (size <= 1024)",
        'OwnTrace.ScratchSelected("parse", "tmp", size, 1024, "stackalloc");',
        'OwnTrace.ScratchSelected("parse", "tmp", size, 1024, "ArrayPool");',
        "OwnCounters.StackHit();",
        "OwnCounters.PoolFallback(size);",
        "OwnCounters.Requested(size);",
        "OwnCounters.PoolReturned(size);",
        "public static long ScratchTotalRequestedBytes;",
        "public static long ScratchMaxRequestedBytes;",
        "public static long ScratchPoolBytesReturned;",
        "public static long ScratchForcedClears;",
        "ArrayPool<byte>.Shared.Rent(size)",
        "ArrayPool<byte>.Shared.Return(tmp_rented)",
        "try",
        "finally",
        "internal static class OwnTrace",
        "internal static class OwnCounters",
        'Conditional("OWNSHARP_TRACE")',
        'Conditional("OWNSHARP_COUNTERS")',
    ]
    for s in must_contain:
        if s not in out:
            fails.append(f"buffer C# missing: {s!r}")
    # the pool Return must run exactly once, guarded by the rented null-check
    if out.count("ArrayPool<byte>.Shared.Return(tmp_rented)") != 1:
        fails.append("buffer C# should Return the rented array exactly once")

    # compile-time report
    mod = parse(BUFFER_GOLDEN)
    rep = build_report(mod, [])
    if not rep["buffers"]:
        fails.append("buffer report produced no entries")
    else:
        e = rep["buffers"][0]
        if e["mode"] != "scratch" or e["inlineBytes"] != 1024:
            fails.append(f"buffer report has wrong mode/inline: {e}")
        if e["escapePolicy"] != "local-only":
            fails.append(f"scratch report should be local-only, got {e['escapePolicy']}")
        backends = {b["backend"] for b in e["branches"]}
        if backends != {"stackalloc", "ArrayPool"}:
            fails.append(f"scratch report branches wrong: {backends}")

    # the committed runnable golden must stay in sync with the emitter and stay
    # a real, compilable ArrayPool program (a human can `dotnet run` it).
    golden_path = os.path.join(os.path.dirname(__file__),
                               "buffer_scratch_program.cs.txt")
    if os.path.exists(golden_path):
        with open(golden_path, encoding="utf-8") as f:
            prog = f.read()
        for s in ("public static void parse(int size)",
                  "if (size < 0)",
                  "ArrayPool<byte>.Shared.Rent(size)",
                  "ArrayPool<byte>.Shared.Return(tmp_rented)",
                  "internal static class OwnTrace",
                  "internal static class OwnCounters",
                  "public static void Main()"):
            if s not in prog:
                fails.append(f"runnable golden missing: {s!r}")
        # the negative-size guard must precede the trace/counter hooks
        if "if (size < 0)" in prog and "ScratchSelected" in prog:
            if prog.index("if (size < 0)") > prog.index("ScratchSelected"):
                fails.append("runnable golden guard must precede the trace hook")
        # its emitted parse body must match what the emitter produces today
        if "tmp = tmp_backing[..size];" not in prog:
            fails.append("runnable golden parse body drifted from the emitter")
    else:
        fails.append("runnable golden buffer_scratch_program.cs.txt is missing")
    return fails


def escape_and_length_smoke() -> list[str]:
    """Regression guards for the PR #2 review:
    - the checker rejects an escaping movable (pooled/native) buffer rather than
      letting codegen emit C# that leaks the rent or fails to compile (OWN017);
    - a constant scratch smaller than its inline limit exposes the requested
      length, not the reservation;
    - a fallback-forbidden scratch reports as stack-only."""
    fails: list[str] = []

    pooled_ret = ("module M\n"
                  "fn f(n: int) -> Buffer { let b = Buffer.pooled(n); return b; }\n")
    if "OWN017" not in codes(pooled_ret):
        fails.append("escaping pooled (return) must be rejected with OWN017")

    pooled_consume = ("module M\nextern fn Store(consume Buffer);\n"
                      "fn f(n: int){ let b = Buffer.pooled(n); Store(b); }\n")
    if "OWN017" not in codes(pooled_consume):
        fails.append("escaping pooled (consume) must be rejected with OWN017")

    native_ret = ("module M\n"
                  "fn f(n: int) -> Buffer { let b = Buffer.native(n); return b; }\n")
    if "OWN017" not in codes(native_ret):
        fails.append("escaping native (return) must be rejected with OWN017")

    # a locally-released pooled buffer is fine and DOES Return to the pool
    pooled_local = ("module M\nextern fn Fill(borrow_mut Buffer);\n"
                    "fn f(n: int){ let b = Buffer.pooled(n); "
                    "borrow_mut b as m { Fill(m); } release b; }\n")
    if codes(pooled_local):
        fails.append(f"local pooled buffer should check clean, got {codes(pooled_local)}")
    if "ArrayPool<byte>.Shared.Return" not in generate(parse(pooled_local)):
        fails.append("local pooled buffer must Return to the pool")

    scratch_const = ("module M\nextern fn Fill(borrow_mut Buffer);\n"
                     "fn f(){ let b = Buffer.scratch(64, inline = 1024, "
                     "fallback = forbidden); borrow_mut b as m { Fill(m); } "
                     "release b; }\n")
    out = generate(parse(scratch_const))
    if "b_backing[..64]" not in out:
        fails.append("constant forbidden-fallback scratch must expose length 64")

    rep = build_report(parse(scratch_const), [])
    e = rep["buffers"][0]
    if e["fallback"] != "forbidden":
        fails.append("forbidden scratch report fallback should be "
                     f"'forbidden', got {e['fallback']}")
    backends = {b["backend"] for b in e["branches"]}
    if backends != {"stackalloc"}:
        fails.append(f"forbidden scratch report should be stack-only, got {backends}")
    return fails


def branchy_and_malformed_smoke() -> list[str]:
    """Two follow-up review guards:
    - a buffer released inside branches is NOT an escape: codegen must emit the
      real pool cleanup at each release site, never a generic Dispose on a Span;
    - the report must skip a malformed buffer mode (Buffer.bogus) instead of
      throwing, leaving the checker's OWN030 to stand."""
    fails: list[str] = []

    branchy = ("module M\n"
               "fn f(n: int){ let b = Buffer.pooled(n); "
               "if (c) { release b; } else { release b; } }\n")
    if codes(branchy):
        fails.append(f"branchy buffer release should check clean, got {codes(branchy)}")
    out = generate(parse(branchy))
    if "Dispose()" in out:
        fails.append("branchy buffer release must not emit a generic Dispose()")
    if out.count("ArrayPool<byte>.Shared.Return(b_array)") != 2:
        fails.append("branchy pooled release must Return at both release sites")
    if "ArrayPool<byte>.Shared.Rent(n)" not in out:
        fails.append("branchy pooled buffer must still Rent once")

    bogus = parse("module M\nfn f(n: int){ let b = Buffer.bogus(n); release b; }\n")
    try:
        rep = build_report(bogus, [])
    except Exception as e:
        fails.append(f"report crashed on a malformed buffer mode: {type(e).__name__}: {e}")
    else:
        if rep["buffers"]:
            fails.append("report should skip an unresolved buffer mode")

    # overlapping buffer lifetimes released in non-LIFO (FIFO) order must lower
    # without a CodegenError, and both arrays must be returned to the pool.
    fifo = ("module M\nfn f(n: int){ let a = Buffer.pooled(n); "
            "let b = Buffer.pooled(n); release a; release b; }\n")
    if codes(fifo):
        fails.append(f"FIFO overlapping buffers should check clean, got {codes(fifo)}")
    try:
        out = generate(parse(fifo))
    except Exception as e:
        fails.append(f"FIFO overlapping buffers crashed codegen: {type(e).__name__}: {e}")
    else:
        if out.count("ArrayPool<byte>.Shared.Return(a_array)") != 1:
            fails.append("FIFO: a must be returned to the pool exactly once")
        if out.count("ArrayPool<byte>.Shared.Return(b_array)") != 1:
            fails.append("FIFO: b must be returned to the pool exactly once")

    # a misspelled forbidden-fallback must be diagnosed, never silently pooled
    bad_fb = ("module M\nfn f(n: int){ "
              "let b = Buffer.scratch(n, fallback = forbiden); release b; }\n")
    if "OWN030" not in codes(bad_fb):
        fails.append("misspelled scratch fallback must produce OWN030")

    # an inline override must skip a malformed policy default (override wins) and
    # the effective inline limit must be the override
    ov = ("module M\npolicy P { inline_bytes = bogus; }\n"
          "fn f(n: int){ let b = Buffer.scratch(n, policy = P, inline = 128); "
          "release b; }\n")
    if codes(ov):
        fails.append(f"inline override should ignore bad policy default, got {codes(ov)}")
    if "stackalloc byte[128]" not in generate(parse(ov)):
        fails.append("inline override (128) must be the effective inline limit")

    # a non-identifier fallback (fallback = 0) must likewise fail safe: OWN030
    # AND no ArrayPool fallback enabled (it must not silently heap-allocate).
    from ownlang.ast_nodes import BufferIntent, IntLit
    from ownlang.buffers import resolve as _resolve
    intent = BufferIntent(mode="scratch", size=IntLit(8, 1),
                          options={"fallback": IntLit(0, 1)}, line=1)
    info, idiags = _resolve(intent, {})
    if "OWN030" not in {d.code for d in idiags}:
        fails.append("non-identifier scratch fallback must produce OWN030")
    if info.fallback_pool:
        fails.append("non-identifier scratch fallback must not enable the pool")

    # the report's noEscape check must agree with the OWN017 checker diagnostic
    esc = parse("module M\nfn f(n: int) -> Buffer { let b = Buffer.pooled(n); "
                "return b; }\n")
    if _report_check(esc, "noEscape"):
        fails.append("report noEscape must be false for an OWN017-rejected buffer")

    # a buffer released through a moved alias must lower (not raise) and the
    # cleanup must attach to the moved-to name's release.
    moved = ("module M\nfn f(n: int){ let a = Buffer.pooled(n); "
             "let b = move a; release b; }\n")
    if codes(moved):
        fails.append(f"move-then-release buffer should check clean, got {codes(moved)}")
    try:
        out = generate(parse(moved))
    except Exception as e:
        fails.append(f"move-then-release buffer crashed codegen: {type(e).__name__}: {e}")
    else:
        if out.count("ArrayPool<byte>.Shared.Return(a_array)") != 1:
            fails.append("moved buffer must still Return its original backing once")

    # a wrong namespace (Foo.stack) must be diagnosed, not silently lowered
    bad_ns = "module M\nfn f(n: int){ let b = Foo.stack(n, max = 1024); release b; }\n"
    if "OWN030" not in codes(bad_ns):
        fails.append("non-Buffer namespace must produce OWN030")

    # an escape reported on a moved-to alias must fail the buffer's noEscape check
    moved_esc = parse("module M\nfn f(n: int) -> Buffer { "
                      "let a = Buffer.stack(n, max = 100); let b = move a; "
                      "return b; }\n")
    if _report_check(moved_esc, "noEscape"):
        fails.append("report noEscape must be false when a moved alias escapes")
    return fails


def _report_check(mod, check):
    """Run the full checker over a parsed module and return the named report
    check (True/False) for its first buffer."""
    from ownlang.cfg import build_cfg, collect_policies, collect_signatures
    rn = {r.name for r in mod.resources}
    sg = collect_signatures(mod)
    pl = collect_policies(mod)
    diags = []
    for fn in mod.functions:
        cfg, d1 = build_cfg(fn, rn, sg, pl)
        diags += d1 + analyze(cfg)
    rep = build_report(mod, diags)
    return rep["buffers"][0]["checks"][check] if rep["buffers"] else None


def nesting_native_trace_smoke() -> list[str]:
    """Three follow-up review guards:
    - an ordinary resource inside a buffer's lifetime keeps its own finally
      (exception from the body must not leak it while the buffer is returned);
    - a native buffer with a dynamic size guards against a negative request
      before NativeMemory.Alloc;
    - a policy `trace = false` is honoured (no OwnTrace, report trace:false)."""
    fails: list[str] = []

    # Issue 1: buffer + ordinary resource each get their own finally
    mix = ("module M\nresource Conn { acquire open release close }\n"
           "extern fn Work(borrow_mut Buffer);\n"
           "fn f(n: int){ let b = Buffer.scratch(n); let c = acquire Conn(); "
           "Work(b); release c; release b; }\n")
    if codes(mix):
        fails.append(f"buffer+resource should check clean, got {codes(mix)}")
    out = generate(parse(mix))
    if out.count("finally") != 2:
        fails.append(f"buffer+resource must produce two finally blocks, got {out.count('finally')}")
    if "c.close();" not in out:
        fails.append("Conn must be closed")
    elif out.index("c.close();") > out.index("ArrayPool<byte>.Shared.Return"):
        fails.append("Conn finally must be nested inside the buffer's try (close before Return)")

    # Issue 2: native dynamic size guards against a negative request
    nat_dyn = ("module M\nextern fn Fill(borrow_mut Buffer);\n"
               "fn g(n: int){ let b = Buffer.native(n); "
               "borrow_mut b as m { Fill(m); } release b; }\n")
    out = generate(parse(nat_dyn))
    if "if (n < 0)" not in out or "ArgumentOutOfRangeException(nameof(n))" not in out:
        fails.append("native dynamic size must guard against a negative request")
    nat_const = ("module M\nextern fn Fill(borrow_mut Buffer);\n"
                 "fn g(){ let b = Buffer.native(256); "
                 "borrow_mut b as m { Fill(m); } release b; }\n")
    if "< 0" in generate(parse(nat_const)):
        fails.append("native constant size should not emit a negative guard")

    # Issue 3: a policy trace = false disables tracing
    from ownlang.ast_nodes import BufferIntent, VarRef
    from ownlang.buffers import Policy
    from ownlang.buffers import resolve as _resolve
    intent = BufferIntent(mode="scratch", size=VarRef("n", 1),
                          options={"policy": VarRef("Quiet", 1)}, line=1)
    pol = {"Quiet": Policy("Quiet", {"trace": False, "counters": True})}
    info, _ = _resolve(intent, pol)
    if info.trace:
        fails.append("policy trace = false must disable tracing")
    quiet = ("module M\npolicy Quiet { trace = false; }\n"
             "extern fn Fill(borrow_mut Buffer);\n"
             "fn h(n: int){ let b = Buffer.scratch(n, policy = Quiet); "
             "borrow_mut b as m { Fill(m); } release b; }\n")
    hbody = generate(parse(quiet)).split("public static void h")[1].split("internal static")[0]
    if "OwnTrace" in hbody:
        fails.append("policy trace = false must emit no OwnTrace calls")
    return fails


def ordering_counters_smoke() -> list[str]:
    """Three follow-up review guards:
    - a moved buffer's cleanup survives in sibling branches (a `move` in one
      branch must not strip the original's cleanup from the other);
    - pooled buffers do not emit the Scratch.* counters (they would corrupt the
      stack-hit-rate metric);
    - simple-mode keeps a buffer prelude after earlier plain statements it can
      depend on (no Rent(n) before `var n = 64;`)."""
    fails: list[str] = []

    # Issue 1: move in one branch must not strip cleanup from the sibling branch
    sib = ("module M\nfn f(n: int){ let a = Buffer.pooled(n); "
           "if (c) { let b = move a; release b; } else { release a; } }\n")
    if codes(sib):
        fails.append(f"sibling-branch move should check clean, got {codes(sib)}")
    out = generate(parse(sib))
    if "Dispose()" in out:
        fails.append("sibling-branch release must return to the pool, not Dispose")
    if out.count("ArrayPool<byte>.Shared.Return(a_array)") != 2:
        fails.append("both branches must return a_array to the pool")

    # Issue 2: pooled buffers must not touch the Scratch.* counters (check the
    # function body only — the OwnCounters class itself is always emitted)
    pooled = ("module M\nextern fn Fill(borrow_mut Buffer);\n"
              "fn p(n: int){ let b = Buffer.pooled(n); "
              "borrow_mut b as m { Fill(m); } release b; }\n")
    pbody = generate(parse(pooled)).split("public static void p")[1].split("internal static")[0]
    if "OwnCounters" in pbody:
        fails.append("pooled buffer must not emit Scratch.* counters")
    # ...but scratch still must (sanity that the gate is mode-specific)
    scratch = ("module M\nextern fn Fill(borrow_mut Buffer);\n"
               "fn s(n: int){ let b = Buffer.scratch(n); "
               "borrow_mut b as m { Fill(m); } release b; }\n")
    sbody = generate(parse(scratch)).split("public static void s")[1].split("internal static")[0]
    if "OwnCounters.StackHit()" not in sbody:
        fails.append("scratch buffer must still emit Scratch.* counters")

    # Issue 3: a plain statement before a buffer stays before its prelude
    order = "module M\nfn q(){ let n = 64; let b = Buffer.pooled(n); release b; }\n"
    out = generate(parse(order))
    if "var n = 64;" not in out or "Rent(n)" not in out:
        fails.append("ordering smoke missing expected lines")
    elif out.index("var n = 64;") > out.index("Rent(n)"):
        fails.append("buffer prelude must come after the plain statement it depends on")

    # disjoint sequential buffers: a must be returned before b is rented (its
    # source release point must not be swallowed into b's lifetime)
    disj = ("module M\nextern fn Use1(borrow_mut Buffer);\n"
            "fn d(n: int){ let a = Buffer.pooled(n); Use1(a); release a; "
            "let b = Buffer.pooled(n); Use1(b); release b; }\n")
    out = generate(parse(disj))
    if "ArrayPool<byte>.Shared.Return(a_array)" not in out or "b_array = ArrayPool" not in out:
        fails.append("disjoint smoke missing expected lines")
    elif out.index("Return(a_array)") > out.index("b_array = ArrayPool"):
        fails.append("buffer a must be returned before buffer b is rented")

    # a plain local declared in a buffer's body and used after the release must
    # not be trapped in a hoisted try (it would go out of C# scope); the buffer
    # is lowered inline (no try) so the local stays at function scope.
    aftrel = ("module M\nfn f(n: int){ let b = Buffer.pooled(n); let x = 1; "
              "release b; let y = x; }\n")
    if codes(aftrel):
        fails.append(f"local-after-release should check clean, got {codes(aftrel)}")
    body = generate(parse(aftrel)).split("public static void f")[1].split("internal static")[0]
    if "try" in body:
        fails.append("a buffer with a plain local in its body must not be hoisted")
    if "var x = 1;" not in body or "var y = x;" not in body:
        fails.append("local-after-release smoke missing expected lines")
    elif body.index("var x = 1;") > body.index("var y = x;"):
        fails.append("x must be declared before y")

    # a negative scratch size is rejected BEFORE any trace/counter runs
    negsc = ("module M\nextern fn Fill(borrow_mut Buffer);\n"
             "fn g(n: int){ let b = Buffer.scratch(n); "
             "borrow_mut b as m { Fill(m); } release b; }\n")
    out = generate(parse(negsc))
    if "if (n < 0)" not in out:
        fails.append("scratch dynamic size must guard against a negative request")
    elif out.index("if (n < 0)") > out.index("ScratchSelected"):
        fails.append("scratch negative guard must run before any trace/counter")

    # partially-overlapping lifetimes (a released while b still live) must NOT be
    # hoisted into nested try/finally — that would force b's release before its
    # source point. They fall back to faithful inline (release where written).
    overlap = ("module M\nresource A { acquire oa release ca }\n"
               "resource B { acquire ob release cb }\n"
               "fn f(){ let a = acquire A(); let b = acquire B(); "
               "release a; use b; release b; }\n")
    out = generate(parse(overlap))
    if "Use(b)" not in out or "b.cb()" not in out:
        fails.append("overlap smoke missing expected lines")
    elif out.index("Use(b)") > out.index("b.cb()"):
        fails.append("partial overlap must not emit use-after-release for b")
    if "a.ca()" in out and out.index("a.ca()") > out.index("Use(b)"):
        fails.append("a must be released at its source point, before use b")

    # a buffer whose release is nested in another owner's borrow block must NOT
    # be hoisted (that would double-clean: a stray Dispose plus the finally).
    nested = ("module M\nresource Conn { acquire open release close }\n"
              "fn f(n: int){ let a = acquire Conn(1); let b = Buffer.pooled(n); "
              "borrow a as s { release b; } release a; }\n")
    if codes(nested):
        fails.append(f"nested buffer release should check clean, got {codes(nested)}")
    out = generate(parse(nested))
    if "Dispose()" in out:
        fails.append("nested buffer release must not emit a generic Dispose()")
    if out.count("ArrayPool<byte>.Shared.Return(b_array)") != 1:
        fails.append("nested buffer release must return b_array exactly once")

    # native buffers expose a Span<byte> view (so a borrow/call sees the same
    # logical type as pooled/stack), and free the backing pointer on release
    native = ("module M\nextern fn Fill(borrow_mut Buffer);\n"
              "fn g(n: int){ let b = Buffer.native(n); "
              "borrow_mut b as m { Fill(m); } release b; }\n")
    out = generate(parse(native))
    if "new Span<byte>(b_ptr, n)" not in out:
        fails.append("native buffer must expose a Span<byte> view for borrows/calls")
    if "NativeMemory.Free(b_ptr)" not in out:
        fails.append("native release must free the backing pointer")
    if "var m = b;" not in out:
        fails.append("native borrow must bind the span view, not the raw pointer")

    # a moved buffer's cleanup alias must not leak onto a later same-named, but
    # unrelated, resource declared in another scope
    redecl = ("module M\nresource Conn { acquire open release close }\n"
              "fn f(n: int){ let a = Buffer.pooled(n); "
              "if (c) { let b = move a; release b; } else { release a; } "
              "let b = acquire Conn(); release b; }\n")
    if codes(redecl):
        fails.append(f"alias redeclaration should check clean, got {codes(redecl)}")
    out = generate(parse(redecl))
    if "b.close();" not in out:
        fails.append("redeclared Conn must be closed, not treated as the buffer alias")
    if out.count("ArrayPool<byte>.Shared.Return(a_array)") != 2:
        fails.append("a_array must be returned exactly once per branch (no stale alias)")
    return fails


def helper_and_report_smoke() -> list[str]:
    """Two review guards:
    - a local helper with a `&mut Buffer` / `&Buffer` param lowers to a
      Span<byte> / ReadOnlySpan<byte> signature, so passing a buffer value (a
      Span) compiles;
    - the report attributes diagnostics by buffer identity (name#line), so two
      same-named buffers in sibling scopes are not conflated."""
    fails: list[str] = []

    helper = ("module M\nfn helper(x: &mut Buffer){ use x; }\n"
              "fn view(y: &Buffer){ use y; }\n"
              "fn f(n: int){ let b = Buffer.pooled(n); helper(b); view(b); "
              "release b; }\n")
    if codes(helper):
        fails.append(f"local Buffer helper should check clean, got {codes(helper)}")
    out = generate(parse(helper))
    if "public static void helper(Span<byte> x)" not in out:
        fails.append("&mut Buffer param must lower to Span<byte>")
    if "public static void view(ReadOnlySpan<byte> y)" not in out:
        fails.append("&Buffer param must lower to ReadOnlySpan<byte>")
    if "ref Buffer" in out or "ref readonly Buffer" in out:
        fails.append("Buffer borrow params must not lower to ref Buffer")

    # same name in sibling scopes: only the leaking buffer fails releaseOnAllPaths
    sib = ("module M\nfn f(n: int){ if (c) { let b = Buffer.pooled(n); } "
           "else { let b = Buffer.pooled(n); release b; } }\n")
    mod = parse(sib)
    rn = {r.name for r in mod.resources}
    sg = collect_signatures(mod)
    pl = collect_policies(mod)
    diags = list(validate_policies(pl))
    for fn in mod.functions:
        cfg, d1 = build_cfg(fn, rn, sg, pl)
        diags += d1 + analyze(cfg)
    rep = build_report(mod, diags)
    flags = sorted(e["checks"]["releaseOnAllPaths"] for e in rep["buffers"])
    if flags != [False, True]:
        fails.append(f"sibling same-name buffers must be attributed separately, got {flags}")
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
        except Exception as e:
            cg_fail += 1
            print(f"CODEGEN FAIL {name}: {type(e).__name__}: {e}")

    golden_fails = golden_smoke()
    for f in golden_fails:
        print(f"GOLDEN FAIL: {f}")

    buffer_fails = buffer_smoke()
    for f in buffer_fails:
        print(f"BUFFER FAIL: {f}")

    escape_fails = escape_and_length_smoke()
    for f in escape_fails:
        print(f"ESCAPE FAIL: {f}")

    branchy_fails = branchy_and_malformed_smoke()
    for f in branchy_fails:
        print(f"BRANCHY FAIL: {f}")

    nest_fails = nesting_native_trace_smoke()
    for f in nest_fails:
        print(f"NESTING FAIL: {f}")

    order_fails = ordering_counters_smoke()
    for f in order_fails:
        print(f"ORDERING FAIL: {f}")

    helper_fails = helper_and_report_smoke()
    for f in helper_fails:
        print(f"HELPER FAIL: {f}")

    total = passed + failed
    print(f"\nanalysis: {passed}/{total} passed, {failed} failed")
    print(f"codegen:  {cg_total - cg_fail}/{cg_total} generated cleanly")
    print(f"golden:   {'PASS' if not golden_fails else 'FAIL'}")
    print(f"buffer:   {'PASS' if not buffer_fails else 'FAIL'}")
    print(f"escape:   {'PASS' if not escape_fails else 'FAIL'}")
    print(f"branchy:  {'PASS' if not branchy_fails else 'FAIL'}")
    print(f"nesting:  {'PASS' if not nest_fails else 'FAIL'}")
    print(f"ordering: {'PASS' if not order_fails else 'FAIL'}")
    print(f"helper:   {'PASS' if not helper_fails else 'FAIL'}")

    # Content-level codegen assertions + property fuzzer: these inspect the
    # generated C# itself (release placement/count, declaration order), catching
    # lowerings that are silently wrong rather than ones that merely throw.
    import test_codegen
    cc_rc = test_codegen.run()
    import test_codegen_props
    pf_rc = test_codegen_props.run(iterations=3000, seed=1234)

    # The "what it catches" gallery: every examples/gallery/ file must still
    # produce exactly the diagnostic it advertises, so the demo can't drift.
    import test_gallery
    gl_rc = test_gallery.run()

    # Real-world corpus: each case.own (a reduction of a real ArrayPool/Dispose
    # bug) must still produce the diagnostics it documents.
    import test_corpus
    co_rc = test_corpus.run()

    return 1 if (failed or cg_fail or golden_fails or buffer_fails
                 or escape_fails or branchy_fails or nest_fails
                 or order_fails or helper_fails or cc_rc or pf_rc
                 or gl_rc or co_rc) else 0


if __name__ == "__main__":
    raise SystemExit(run())
