#!/usr/bin/env python3
"""
Metamorphic testing for the Own.NET core checker — analyzer QA (no LLM, no oracle).

Generate **semantically-equivalent** variants of a `.own` program — rewrites that
cannot change its meaning — and assert the checker's diagnostics are invariant. A
divergence is a *robustness bug in the analyzer itself*: it keyed on something
semantically irrelevant (a name, a textual order). This finds such bugs with no
labels and no second tool — the StaAgent / Statfier line (testing the analyzer).

It is also the conformance check a future LLM fix-loop needs (reward =
checker-green AND behaviour-preserved), but its value here is standalone: an
automatic robustness tester + a measurable stability metric for the benchmark.

Sound transforms (v1), each provably meaning-preserving:
  - **alpha-rename**: rename a local bound exactly once (no shadowing) and every
    one of its references — pure alpha-equivalence.
  - **reorder**: swap two adjacent *simple* statements whose touched-variable sets
    are disjoint — independent statements commute.

Invariance is compared on the **(code, line) multiset**: alpha-rename can only
move a caret column, and reorder keeps each node's own line, so a *correct*
checker yields the identical set. A difference means order/name sensitivity where
there must be none.

dotnet-free: drives the same parser + core the CLI uses, straight on the AST.

Usage:
  metamorphic.py <file-or-dir> ...     # sweep .own files; report any non-invariance
  metamorphic.py --selftest            # corpus invariance + a teeth test
"""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ownlang.ast_nodes import (
    Acquire,
    BorrowBlock,
    BufferIntent,
    Call,
    If,
    Let,
    Module,
    Move,
    Release,
    Return,
    Subscribe,
    Use,
    VarRef,
    While,
)
from ownlang.lexer import LexError
from ownlang.parser import ParseError, parse

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ownlang.ast_nodes import Expr, FnDecl, Stmt

# --- diagnostic key: what must stay invariant ------------------------------


def diag_key(mod: Module) -> tuple[tuple[str, int], ...]:
    """The (code, line) multiset the checker produces, as a sorted tuple. This is
    the property a meaning-preserving rewrite must not change."""
    from ownlang.__main__ import check_module  # local: avoid an import cycle at load
    return tuple(sorted((d.code, d.line) for d in check_module(mod)))


# --- name occurrences (for substitution and independence) ------------------


def _expr_names(e: Expr) -> set[str]:
    """Variable names an expression references."""
    if isinstance(e, VarRef):
        return {e.name}
    if isinstance(e, Move):
        return {e.var}
    if isinstance(e, Acquire):
        return set().union(set(), *(_expr_names(a) for a in e.args))
    if isinstance(e, BufferIntent):
        names: set[str] = set(_expr_names(e.size)) if e.size is not None else set()
        for v in e.options.values():
            names |= _expr_names(v)
        return names
    return set()  # IntLit


def _sub_expr(e: Expr, old: str, new: str) -> Expr:
    """`e` with every reference to `old` renamed to `new`."""
    if isinstance(e, VarRef):
        return replace(e, name=new) if e.name == old else e
    if isinstance(e, Move):
        return replace(e, var=new) if e.var == old else e
    if isinstance(e, Acquire):
        return replace(e, args=[_sub_expr(a, old, new) for a in e.args])
    if isinstance(e, BufferIntent):
        size = _sub_expr(e.size, old, new) if e.size is not None else None
        return replace(e, size=size,
                       options={k: _sub_expr(v, old, new) for k, v in e.options.items()})
    return e  # IntLit


def _sub_stmt(s: Stmt, old: str, new: str) -> Stmt:
    """`s` with every occurrence of the name `old` (binding or reference) renamed."""
    if isinstance(s, Let):
        return replace(s, name=new if s.name == old else s.name,
                       rhs=_sub_expr(s.rhs, old, new))
    if isinstance(s, Release):
        return replace(s, var=new) if s.var == old else s
    if isinstance(s, Use):
        return replace(s, var=new) if s.var == old else s
    if isinstance(s, Call):
        return replace(s, args=[_sub_expr(a, old, new) for a in s.args])
    if isinstance(s, BorrowBlock):
        return replace(s,
                       owner=new if s.owner == old else s.owner,
                       binding=new if s.binding == old else s.binding,
                       body=[_sub_stmt(x, old, new) for x in s.body])
    if isinstance(s, If):
        return replace(s, then_body=[_sub_stmt(x, old, new) for x in s.then_body],
                       else_body=[_sub_stmt(x, old, new) for x in s.else_body])
    if isinstance(s, While):
        return replace(s, body=[_sub_stmt(x, old, new) for x in s.body])
    if isinstance(s, Return):
        return replace(s, var=new) if s.var == old else s
    if isinstance(s, Subscribe):
        return replace(s, source=new) if s.source == old else s
    return s


def _binding_counts(fn: FnDecl) -> Counter[str]:
    """How many times each name is *bound* in the function (params + lets + borrow
    bindings). A name bound exactly once cannot be shadowing anything, so renaming
    all of its occurrences is sound."""
    counts: Counter[str] = Counter(p.name for p in fn.params)

    def walk(body: list[Stmt]) -> None:
        for s in body:
            if isinstance(s, Let):
                counts[s.name] += 1
            elif isinstance(s, BorrowBlock):
                counts[s.binding] += 1
                walk(s.body)
            elif isinstance(s, If):
                walk(s.then_body)
                walk(s.else_body)
            elif isinstance(s, While):
                walk(s.body)

    walk(fn.body)
    return counts


def _all_names(fn: FnDecl) -> set[str]:
    """Every identifier mentioned in the function — to pick a guaranteed-fresh
    rename target."""
    names = {p.name for p in fn.params}

    def walk(body: list[Stmt]) -> None:
        for s in body:
            if isinstance(s, Let):
                names.add(s.name)
                names.update(_expr_names(s.rhs))
            elif isinstance(s, (Release, Use)):
                names.add(s.var)
            elif isinstance(s, Call):
                for a in s.args:
                    names.update(_expr_names(a))
            elif isinstance(s, Subscribe):
                names.add(s.source)
            elif isinstance(s, Return) and s.var is not None:
                names.add(s.var)
            elif isinstance(s, BorrowBlock):
                names.add(s.owner)
                names.add(s.binding)
                walk(s.body)
            elif isinstance(s, If):
                walk(s.then_body)
                walk(s.else_body)
            elif isinstance(s, While):
                walk(s.body)

    walk(fn.body)
    return names


def _rename_fn(fn: FnDecl, old: str, new: str) -> FnDecl:
    params = [replace(p, name=new) if p.name == old else p for p in fn.params]
    return replace(fn, params=params, body=[_sub_stmt(s, old, new) for s in fn.body])


def _with_fn(mod: Module, idx: int, fn: FnDecl) -> Module:
    fns = list(mod.functions)
    fns[idx] = fn
    return replace(mod, functions=fns)


# --- transforms ------------------------------------------------------------


def alpha_rename_variants(mod: Module) -> Iterator[tuple[str, Module]]:
    """One variant per locally-renameable name (bound exactly once, not `self`):
    that name and all its references swapped for a fresh one. Pure alpha-equivalence."""
    for i, fn in enumerate(mod.functions):
        counts = _binding_counts(fn)
        used = _all_names(fn)
        for name, n in counts.items():
            if n != 1 or name == "self":
                continue
            fresh = f"{name}_mr"
            while fresh in used:
                fresh += "x"
            yield (f"{fn.name}: rename {name}->{fresh}",
                   _with_fn(mod, i, _rename_fn(fn, name, fresh)))


def _touches(s: Stmt) -> set[str] | None:
    """The variables a *simple* statement reads or writes, or None if it is not a
    simple, reorderable statement (control flow / borrow blocks are excluded)."""
    if isinstance(s, Let):
        return {s.name} | _expr_names(s.rhs)
    if isinstance(s, (Release, Use)):
        return {s.var}
    if isinstance(s, Call):
        return set().union(set(), *(_expr_names(a) for a in s.args))
    if isinstance(s, Subscribe):
        return {s.source, "self"}
    return None  # If / While / BorrowBlock / Return — not reordered in v1


def reorder_variants(mod: Module) -> Iterator[tuple[str, Module]]:
    """One variant per adjacent pair of simple statements with disjoint touched
    sets, in a function's top-level body: the two are swapped. Independent
    statements commute, so the verdict must not move."""
    for i, fn in enumerate(mod.functions):
        body = fn.body
        for j in range(len(body) - 1):
            ta, tb = _touches(body[j]), _touches(body[j + 1])
            if ta is None or tb is None or not ta.isdisjoint(tb):
                continue
            swapped = list(body)
            swapped[j], swapped[j + 1] = swapped[j + 1], swapped[j]
            yield (f"{fn.name}: swap stmts @{body[j].line}/{body[j + 1].line}",
                   _with_fn(mod, i, replace(fn, body=swapped)))


_TRANSFORMS = (alpha_rename_variants, reorder_variants)


# --- the check ------------------------------------------------------------


def violations(src: str) -> list[str]:
    """Every metamorphic violation for one `.own` source: a meaning-preserving
    variant whose diagnostics differ from the original. Empty == robust."""
    try:
        mod = parse(src)
    except (ParseError, LexError):
        return []  # a non-parsing program is out of scope, not a violation
    base = diag_key(mod)
    out: list[str] = []
    for transform in _TRANSFORMS:
        for label, variant in transform(mod):
            try:
                got = diag_key(variant)
            except Exception as e:  # a crash on a valid variant is itself a finding
                out.append(f"{label}: variant raised {type(e).__name__}: {e}")
                continue
            if got != base:
                out.append(f"{label}: base={list(base)} variant={list(got)}")
    return out


def sweep(paths: list[str]) -> int:
    """Run the harness over every .own file under the given files/dirs. Returns the
    number of files with a violation (0 == all robust)."""
    files: list[Path] = []
    for p in paths:
        pp = Path(p)
        files.extend(sorted(pp.rglob("*.own")) if pp.is_dir() else [pp])
    bad = 0
    for f in files:
        try:
            vs = violations(f.read_text(encoding="utf-8"))
        except OSError as e:
            print(f"{f}: cannot read ({e})")
            continue
        if vs:
            bad += 1
            print(f"\n{f}: {len(vs)} metamorphic violation(s):")
            for v in vs:
                print(f"  - {v}")
    n = len(files)
    print(f"\nmetamorphic: {n - bad}/{n} file(s) invariant under "
          f"{len(_TRANSFORMS)} transform class(es).")
    return 1 if bad else 0


# --- selftest -------------------------------------------------------------


def _selftest() -> int:
    fails: list[str] = []
    repo = Path(__file__).resolve().parent.parent

    # 1) Robustness: the gallery + examples + corpus must be invariant under every
    #    transform. (Deduped by resolved path so a nested dir isn't swept twice.)
    roots = [repo / "examples", repo / "corpus"]
    files = sorted({f.resolve() for r in roots if r.exists() for f in r.rglob("*.own")})
    total_files = len(files)
    for f in files:
        vs = violations(f.read_text(encoding="utf-8"))
        if vs:
            fails.append(f"{f.name} not invariant: {vs[0]}")
    if total_files == 0:
        fails.append("no corpus .own files found to sweep")

    # 2) Teeth: the (code, line) key must actually distinguish a leak from a clean
    #    run — otherwise "zero violations" would be vacuous (a blind, constant key).
    leak = "module M\nresource R { acquire a release r }\nfn f() { let x = acquire R(1); }\n"
    clean = ("module M\nresource R { acquire a release r }\n"
             "fn f() { let x = acquire R(1); release x; }\n")
    if diag_key(parse(leak)) == diag_key(parse(clean)):
        fails.append("teeth: key does not distinguish a leak from a clean run")
    if not any(c == "OWN001" for c, _ in diag_key(parse(leak))):
        fails.append("teeth: expected OWN001 on the leak fixture")

    # 3) The transforms actually fire (a rename + a reorder are generated on a
    #    program that admits them) — so the sweep is not silently a no-op.
    prog = ("module M\nresource R { acquire a release r }\nextern fn S(borrow R);\n"
            "fn f() { let x = acquire R(1); let y = acquire R(2); "
            "release x; release y; }\n")
    m = parse(prog)
    n_alpha = sum(1 for _ in alpha_rename_variants(m))
    n_reorder = sum(1 for _ in reorder_variants(m))
    if n_alpha < 2:
        fails.append(f"expected >=2 alpha-rename variants, got {n_alpha}")
    if n_reorder < 1:
        fails.append(f"expected >=1 reorder variant, got {n_reorder}")
    # and that program is itself invariant (x and y are independent leaks).
    if violations(prog):
        fails.append(f"two-independent-leaks program should be invariant: {violations(prog)}")

    for msg in fails:
        print(f"METAMORPHIC SELFTEST FAIL: {msg}")
    passed = 6 - len(fails)
    print(f"metamorphic selftest: {passed}/6 checks passed "
          f"(swept {total_files} corpus file(s))")
    return 1 if fails else 0


def main(argv: list[str]) -> int:
    if argv == ["--selftest"]:
        return _selftest()
    if not argv or any(a.startswith("-") for a in argv):
        print(__doc__)
        return 2
    return sweep(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
