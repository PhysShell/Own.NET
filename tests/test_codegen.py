#!/usr/bin/env python3
"""
Codegen-focused regression suite for the OwnLang PoC.

The suite in ``run_tests.py`` proves the *analyzer* assigns the right diagnostic
codes, and its codegen smoke only checks that ``generate`` does not throw. That
is not enough: every codegen bug found so far produced **valid-looking C# that
silently does the wrong thing** (a double-free, a leak, a use-before-declaration)
without raising. So this file asserts on the *content* of the generated C#.

Each case first re-checks that the source is clean at the ownership level (we
only lower programs the checker accepted), then asserts structural facts about
the emitted C#.

Run:  python tests/run_tests.py        (invokes these too)
      python tests/test_codegen.py     (standalone)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.parser import parse                          # noqa: E402
from ownlang.cfg import build_cfg, collect_signatures     # noqa: E402
from ownlang.analysis import analyze                       # noqa: E402
from ownlang.diagnostics import Severity                   # noqa: E402
from ownlang.codegen import generate                       # noqa: E402


# Schematic prelude: resource Buffer renders as Buffer.rent(...) / x.give().
SCHEMATIC = (
    "module M\n"
    "resource Buffer { acquire rent release give }\n"
    "extern fn Fill(borrow_mut Buffer);\n"
    "extern fn Hash(borrow Buffer);\n"
    "extern fn Store(consume Buffer);\n"
)

# ArrayPool prelude: the same Buffer lowered to real .NET via emit_* templates.
ARRAYPOOL = (
    "module M\n"
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
    "extern fn Store(consume Buffer);\n"
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _errors(src: str) -> list[str]:
    mod = parse(src)
    rnames = {r.name for r in mod.resources}
    sigs = collect_signatures(mod)
    out: list[str] = []
    for fn in mod.functions:
        cfg, d1 = build_cfg(fn, rnames, sigs)
        d2 = analyze(cfg)
        out += [d.code for d in (d1 + d2) if d.severity == Severity.ERROR]
    return out


class Check:
    """A tiny fluent assertion helper over the generated C# of one program."""

    def __init__(self, name: str, prelude: str, fn_src: str):
        self.name = name
        self.fails: list[str] = []
        src = prelude + fn_src
        errs = _errors(src)
        if errs:
            self.fails.append(f"source is not clean, got {sorted(set(errs))}")
            self.cs = ""
        else:
            self.cs = generate(parse(src))

    # -- assertions ---------------------------------------------------------

    def has(self, needle: str) -> "Check":
        if needle not in self.cs:
            self.fails.append(f"expected to contain {needle!r}")
        return self

    def lacks(self, needle: str) -> "Check":
        if needle in self.cs:
            self.fails.append(f"expected NOT to contain {needle!r}")
        return self

    def count(self, needle: str, n: int) -> "Check":
        got = self.cs.count(needle)
        if got != n:
            self.fails.append(f"expected {needle!r} x{n}, got x{got}")
        return self

    def before(self, a: str, b: str) -> "Check":
        """`a` must appear, and its first occurrence must precede `b`'s."""
        ia, ib = self.cs.find(a), self.cs.find(b)
        if ia < 0:
            self.fails.append(f"ordering: {a!r} missing")
        elif ib < 0:
            self.fails.append(f"ordering: {b!r} missing")
        elif ia >= ib:
            self.fails.append(f"ordering: expected {a!r} before {b!r}")
        return self

    def release_is_hoisted(self, give: str) -> "Check":
        """`give` (a release call) must sit inside a `finally`, exactly once,
        and not also be duplicated in the `try` body."""
        self.has("try").has("finally").count(give, 1)
        gi = self.cs.find(give)
        fi = self.cs.rfind("finally", 0, gi)
        if fi < 0:
            self.fails.append(f"{give!r} is not inside a finally block")
        return self


_REGISTRY: list[Check] = []


def case(name: str, prelude: str, fn_src: str) -> Check:
    c = Check(name, prelude, fn_src)
    _REGISTRY.append(c)
    return c


# ---------------------------------------------------------------------------
# Bug C — double-free: an acquired resource that ESCAPES via a consume-call
# must NOT get a hoisted `finally` release.
# ---------------------------------------------------------------------------

case("consume_no_release", SCHEMATIC,
     "fn f(){ let b = acquire Buffer(1); Store(b); }") \
    .has("Store(b);").lacks(".give(").lacks("finally")

case("consume_among_releases", SCHEMATIC,
     "fn f(){ let a = acquire Buffer(1); let b = acquire Buffer(2); "
     "release a; Store(b); }") \
    .has("Store(b);").has("a.give();").lacks("b.give(")

case("arraypool_consume_no_return", ARRAYPOOL,
     "fn f(){ let b = acquire Buffer(1); Store(b); }") \
    .has("ArrayPool<byte>.Shared.Rent(1)") \
    .has("Store(b);") \
    .lacks("ArrayPool<byte>.Shared.Return")


# ---------------------------------------------------------------------------
# Bug A — leak: a released owned PARAMETER must actually be released (it has no
# matching acquire, so the old hoist dropped it entirely).
# ---------------------------------------------------------------------------

case("param_release", SCHEMATIC, "fn f(b: Buffer){ release b; }") \
    .count("b.give();", 1)

case("param_release_with_acquire", SCHEMATIC,
     "fn f(b: Buffer){ let a = acquire Buffer(1); release a; release b; }") \
    .count("a.give();", 1).count("b.give();", 1)

case("arraypool_param_release", ARRAYPOOL, "fn f(b: Buffer){ release b; }") \
    .count("ArrayPool<byte>.Shared.Return(b)", 1)

# A param that is consumed (not released) plus a locally-acquired resource: the
# local still hoists into a try/finally, the param is consumed inline, and the
# param is NOT released.
case("acquire_hoists_param_consumed", SCHEMATIC,
     "fn f(b: Buffer){ let a = acquire Buffer(1); release a; Store(b); }") \
    .release_is_hoisted("a.give();").has("Store(b);").lacks("b.give(")


# ---------------------------------------------------------------------------
# Bug B — use-before-declaration: an acquire whose argument is a preceding local
# must not be hoisted above that local.
# ---------------------------------------------------------------------------

case("acquire_arg_local_order", SCHEMATIC,
     "fn f(){ let n = 5; let a = acquire Buffer(n); release a; }") \
    .before("var n = 5;", "Buffer.rent(n)").has("a.give();")

# But an acquire whose argument is a parameter is free to hoist.
case("acquire_arg_param_hoists", SCHEMATIC,
     "fn f(sz: int){ let a = acquire Buffer(sz); release a; }") \
    .release_is_hoisted("a.give();").has("Buffer.rent(sz)")


# ---------------------------------------------------------------------------
# Hoist path stays correct for the straight-line cases it was designed for.
# ---------------------------------------------------------------------------

case("hoist_single", SCHEMATIC,
     "fn f(){ let b = acquire Buffer(10); release b; }") \
    .release_is_hoisted("b.give();").before("Buffer.rent(10)", "try")

# Two resources with crossing lifetimes are not laminar, so this codegen
# emits them inline (faithful release at each site) rather than nested
# try/finally. Either way each is released exactly once.
case("two_resources_each_released_once", SCHEMATIC,
     "fn f(){ let a = acquire Buffer(1); let b = acquire Buffer(2); "
     "release a; release b; }") \
    .count("a.give();", 1).count("b.give();", 1)

# Borrows inside a hoisted body render via emit_borrow and stay inside the try.
case("hoist_with_borrows", SCHEMATIC,
     "fn f(){ let b = acquire Buffer(1); borrow_mut b as m { Fill(m); } "
     "borrow b as r { Hash(r); } release b; }") \
    .release_is_hoisted("b.give();").has("Fill(m)").has("Hash(r)") \
    .before("Fill(m)", "b.give();")


# ---------------------------------------------------------------------------
# Inline path: move / owned-return / branches.
# ---------------------------------------------------------------------------

case("move_inline", SCHEMATIC,
     "fn f(){ let a = acquire Buffer(1); let c = move a; release c; }") \
    .has("// ownership moved from a").count("c.give();", 1).lacks("a.give(") \
    .lacks("finally")

case("owned_return_inline", SCHEMATIC,
     "fn f() -> Buffer { let b = acquire Buffer(1); return b; }") \
    .has("return b;").lacks(".give(").lacks("finally") \
    .has("public static Buffer f(")

case("branch_release_both_arms", SCHEMATIC,
     "fn f(){ let b = acquire Buffer(1); if (c) { release b; } "
     "else { release b; } }") \
    .has("if (c)").has("else").count("b.give();", 2).lacks("finally")

case("branch_release_one_arm_consume_other", SCHEMATIC,
     "fn f(){ let b = acquire Buffer(1); if (c) { release b; } "
     "else { Store(b); } }") \
    .count("b.give();", 1).has("Store(b);")


# ---------------------------------------------------------------------------
# emit_* templates → real .NET, and signature type rendering.
# ---------------------------------------------------------------------------

case("arraypool_golden", ARRAYPOOL,
     "fn process(size: int){ let buf = acquire Buffer(size); "
     "borrow_mut buf as bytes { Fill(bytes); } "
     "borrow buf as view { Hash(view); } release buf; }") \
    .has("using System.Buffers;") \
    .has("byte[] buf = ArrayPool<byte>.Shared.Rent(size);") \
    .release_is_hoisted("ArrayPool<byte>.Shared.Return(buf);") \
    .has("buf.AsSpan()").has("Fill(bytes)").has("Hash(view)")

# A borrowed Buffer lowers to its span view (Span<byte> / ReadOnlySpan<byte>),
# the same view emit_borrow and buffer intents produce.
case("sig_shared_borrow_param", SCHEMATIC, "fn f(x: &Buffer){ use x; }") \
    .has("public static void f(ReadOnlySpan<byte> x)")

case("sig_mut_borrow_param", SCHEMATIC, "fn g(x: &mut Buffer){ Fill(x); }") \
    .has("public static void g(Span<byte> x)")

case("sig_plain_param", SCHEMATIC, "fn f(n: int){ }") \
    .has("public static void f(int n)")

# Two functions land in the same static class.
case("two_functions", SCHEMATIC,
     "fn a(){ let b = acquire Buffer(1); release b; } "
     "fn c(){ let d = acquire Buffer(2); release d; }") \
    .has("static void a(").has("static void c(")


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------


def run() -> int:
    passed = failed = 0
    for c in _REGISTRY:
        if c.fails:
            failed += 1
            print(f"CODEGEN FAIL {c.name}")
            for f in c.fails:
                print(f"     {f}")
        else:
            passed += 1
    total = passed + failed
    print(f"codegen content: {passed}/{total} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
