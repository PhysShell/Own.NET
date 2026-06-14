#!/usr/bin/env python3
"""
Property-based codegen fuzzer for the OwnLang PoC.

Hand-written cases only cover the bugs we already thought of. This file instead
generates many random *clean* programs and, for every one the checker accepts,
asserts invariants about the generated C# that are computed **independently from
the AST** — a separate, much simpler implementation than codegen — so a bug in
codegen cannot be masked by the same bug in the oracle.

Invariants checked on every clean program:

  P1  generation does not throw.
  P2  `try` and `finally` counts are equal, and all braces balance.
  P3  release accounting: for every variable v, the number of `release v;`
      statements in the source equals the number of release-calls on v in the
      generated C#. A dropped owned-parameter release makes this 1 != 0
      (leak); a `finally` release of a consumed/returned resource makes it
      0 != 1 (double-free / use-after-escape).
  P4  declaration-before-use: every local C# introduces (`var X =`) appears
      textually before any other use of X — catches an `acquire Buffer(n)`
      being hoisted above `var n = ...;`.

The generator is constructive: each owned resource is given exactly one "fate"
(release / consume / move-then-release / return), so programs are clean by
construction; the checker is still applied as a filter and non-clean draws are
skipped. Coverage is asserted at the end (both codegen paths and each fate must
actually be exercised), so the run can never pass vacuously.

Run:  python tests/test_codegen_props.py [iterations] [seed]
      python tests/run_tests.py                 (invokes a fixed-seed run)
"""

from __future__ import annotations

import os
import random
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang import ast_nodes as A                         # noqa: E402
from ownlang.parser import parse                           # noqa: E402
from ownlang.cfg import build_cfg, collect_signatures      # noqa: E402
from ownlang.analysis import analyze                        # noqa: E402
from ownlang.diagnostics import Severity                    # noqa: E402
from ownlang.codegen import generate                        # noqa: E402


PRELUDE = (
    "module M\n"
    "resource Buffer { acquire rent release give }\n"
    "extern fn Fill(borrow_mut Buffer);\n"
    "extern fn Hash(borrow Buffer);\n"
    "extern fn Store(consume Buffer);\n"
)


# ---------------------------------------------------------------------------
# random clean-by-construction program generator
# ---------------------------------------------------------------------------


class Gen:
    def __init__(self, rng: random.Random):
        self.rng = rng
        self.n = 0
        self.plain_locals: list[str] = []   # int locals usable as acquire args
        self.coverage: set[str] = set()

    def fresh(self, p: str) -> str:
        self.n += 1
        return f"{p}{self.n}"

    def fn(self) -> tuple[str, set[str]]:
        """Return (function source, coverage-tags hit)."""
        self.coverage = set()
        params: list[str] = []          # (name, owned?)
        owned: list[str] = []           # names of owned values still needing a fate
        lines: list[str] = []

        # parameters: a mix of plain ints, borrows, and owned resources.
        n_params = self.rng.randint(0, 2)
        psig: list[str] = []
        for _ in range(n_params):
            kind = self.rng.choice(["int", "owned", "shared", "mut"])
            nm = self.fresh("p")
            if kind == "int":
                psig.append(f"{nm}: int")
                self.plain_locals.append(nm)
            elif kind == "owned":
                psig.append(f"{nm}: Buffer")
                owned.append(nm)
                self.coverage.add("owned_param")
            elif kind == "shared":
                psig.append(f"{nm}: &Buffer")
            else:
                psig.append(f"{nm}: &mut Buffer")

        # an optional leading plain local, sometimes used as an acquire arg.
        if self.rng.random() < 0.5:
            nm = self.fresh("k")
            lines.append(f"  let {nm} = {self.rng.randint(0, 99)};")
            self.plain_locals.append(nm)

        # acquire a few owned locals.
        for _ in range(self.rng.randint(0, 3)):
            nm = self.fresh("a")
            arg = self._acquire_arg()
            lines.append(f"  let {nm} = acquire Buffer({arg});")
            owned.append(nm)

        # some borrow blocks / temporary-borrow calls over live owned values.
        if owned:
            for _ in range(self.rng.randint(0, 2)):
                v = self.rng.choice(owned)
                stmt = self.rng.choice(["borrow", "borrow_mut", "Hash", "Fill", "use"])
                b = self.fresh("s")
                if stmt == "borrow":
                    lines.append(f"  borrow {v} as {b} {{ use {b}; }}")
                elif stmt == "borrow_mut":
                    lines.append(f"  borrow_mut {v} as {b} {{ Fill({b}); }}")
                elif stmt == "Hash":
                    lines.append(f"  Hash({v});")
                elif stmt == "Fill":
                    lines.append(f"  Fill({v});")
                else:
                    lines.append(f"  use {v};")

        # choose a return value (owned) sometimes.
        ret = ""
        returned: str | None = None
        if owned and self.rng.random() < 0.3:
            returned = self.rng.choice(owned)
            ret = " -> Buffer"
            self.coverage.add("return")

        # give every owned value exactly one fate.
        for v in owned:
            if v == returned:
                continue
            self._emit_fate(v, lines)

        if returned is not None:
            lines.append(f"  return {returned};")

        name = self.fresh("f")
        sig = ", ".join(psig)
        body = "\n".join(lines)
        src = f"fn {name}({sig}){ret} {{\n{body}\n}}\n"
        return src, set(self.coverage)

    def _acquire_arg(self) -> str:
        if self.plain_locals and self.rng.random() < 0.5:
            self.coverage.add("acquire_arg_local")
            return self.rng.choice(self.plain_locals)
        return str(self.rng.randint(0, 99))

    def _emit_fate(self, v: str, lines: list[str]) -> None:
        fate = self.rng.choice(["release", "release", "consume", "move", "branch"])
        if fate == "release":
            lines.append(f"  release {v};")
            self.coverage.add("release")
        elif fate == "consume":
            lines.append(f"  Store({v});")
            self.coverage.add("consume")
        elif fate == "move":
            w = self.fresh("m")
            lines.append(f"  let {w} = move {v};")
            lines.append(f"  release {w};")
            self.coverage.add("move")
        else:  # branch: release on both arms (clean), exercises the inline path
            lines.append(f"  if (cond) {{ release {v}; }} else {{ release {v}; }}")
            self.coverage.add("branch")


# ---------------------------------------------------------------------------
# independent oracle (reads the AST, not the codegen)
# ---------------------------------------------------------------------------


def _walk(stmts: list, fn) -> None:
    for st in stmts:
        fn(st)
        if isinstance(st, A.If):
            _walk(st.then_body, fn)
            _walk(st.else_body, fn)
        elif isinstance(st, A.BorrowBlock):
            _walk(st.body, fn)


def source_release_counts(fn: A.FnDecl) -> dict[str, int]:
    counts: dict[str, int] = {}

    def visit(st) -> None:
        if isinstance(st, A.Release):
            counts[st.var] = counts.get(st.var, 0) + 1

    _walk(fn.body, visit)
    return counts


def all_names(fn: A.FnDecl) -> set[str]:
    names = {p.name for p in fn.params}

    def visit(st) -> None:
        if isinstance(st, A.Let):
            names.add(st.name)
        elif isinstance(st, A.BorrowBlock):
            names.add(st.binding)

    _walk(fn.body, visit)
    return names


# ---------------------------------------------------------------------------
# invariant checks against generated C#
# ---------------------------------------------------------------------------


def check_invariants(fn: A.FnDecl, cs: str) -> list[str]:
    fails: list[str] = []

    # Strip `// ...` line comments first: codegen annotates borrows and moves
    # with the source name (`// mutable borrow of a as s`, `// ownership moved
    # from a`), and those mentions are not C# uses of the variable.
    cs = re.sub(r"//[^\n]*", "", cs)

    # P2: try/finally balance and brace balance.
    if cs.count("try") != cs.count("finally"):
        fails.append(f"try({cs.count('try')}) != finally({cs.count('finally')})")
    if cs.count("{") != cs.count("}"):
        fails.append("unbalanced braces")

    # P3: per-variable release accounting.
    src = source_release_counts(fn)
    for name in all_names(fn):
        want = src.get(name, 0)
        got = len(re.findall(rf"\b{re.escape(name)}\.give\(", cs))
        if want != got:
            fails.append(f"release count for {name!r}: source={want} emitted={got}")

    # P4: declaration-before-use for codegen-introduced locals.
    for m in re.finditer(r"(?:var|byte\[\])\s+(\w+)\s*=", cs):
        nm = m.group(1)
        first = re.search(rf"\b{re.escape(nm)}\b", cs)
        if first and first.start() < m.start():
            fails.append(f"{nm!r} used at {first.start()} before declaration at {m.start()}")

    return fails


def _is_clean(src: str) -> bool:
    mod = parse(src)
    rnames = {r.name for r in mod.resources}
    sigs = collect_signatures(mod)
    for fn in mod.functions:
        cfg, d1 = build_cfg(fn, rnames, sigs)
        d2 = analyze(cfg)
        if any(d.severity == Severity.ERROR for d in (d1 + d2)):
            return False
    return True


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------


def run(iterations: int = 4000, seed: int = 1234) -> int:
    rng = random.Random(seed)
    clean = 0
    hoist = inline = 0
    coverage: set[str] = set()
    failures: list[tuple[str, list[str]]] = []

    for _ in range(iterations):
        gen = Gen(rng)
        fn_src, cov = gen.fn()
        src = PRELUDE + fn_src
        try:
            if not _is_clean(src):
                continue
        except Exception:  # noqa: BLE001  (malformed draw -> skip)
            continue
        clean += 1
        coverage |= cov

        mod = parse(src)
        try:
            cs = generate(mod)              # P1: must not throw
        except Exception as e:              # noqa: BLE001
            failures.append((fn_src, [f"generate threw {type(e).__name__}: {e}"]))
            continue

        if "try" in cs:
            hoist += 1
        else:
            inline += 1

        fails = check_invariants(mod.functions[0], cs)
        if fails:
            failures.append((fn_src, fails))

    # report
    for fn_src, fails in failures[:10]:
        print("PROP FAIL ----------------------------------------------------")
        print(fn_src.rstrip())
        for f in fails:
            print(f"     {f}")

    print(f"property fuzz: {clean} clean programs checked "
          f"({hoist} hoist, {inline} inline), {len(failures)} failed")

    # the run must not be vacuous: both paths and every fate must be exercised.
    need = {"release", "consume", "move", "branch", "owned_param",
            "acquire_arg_local", "return"}
    missing = need - coverage
    coverage_ok = clean > 200 and hoist > 0 and inline > 0 and not missing
    if not coverage_ok:
        print(f"COVERAGE WEAK: clean={clean} hoist={hoist} inline={inline} "
              f"missing={sorted(missing)}")

    return 1 if (failures or not coverage_ok) else 0


if __name__ == "__main__":
    it = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
    sd = int(sys.argv[2]) if len(sys.argv) > 2 else 1234
    raise SystemExit(run(it, sd))
