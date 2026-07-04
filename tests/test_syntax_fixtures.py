#!/usr/bin/env python3
"""Shared syntax parity fixtures (P-022 migration step 2) — Python side.

The Rust `own-syntax` crate must accept exactly what `ownlang.parser.parse`
accepts, reject exactly what it rejects, and render **byte-identical error
text** (`str(LexError)` / `str(ParseError)`, including CPython `repr()`
quoting of the offending token). Copy-pasted expectations rot, so both sides
assert the same corpus: `tests/fixtures/syntax_parity.json`.

* Python is authoritative: `python tests/test_syntax_fixtures.py --write`
  regenerates the file from `CASES` by *running* the real lexer/parser; this
  test (`run()`) fails if the committed file is stale.
* Rust replays it: `rust/crates/own-syntax/tests/parity.rs` parses each
  source and asserts the same outcome — the exact error string, or, for
  accepted programs, the same structural digest (see `_digest`).

The digest is deliberately small (counts + the opaque if/while condition
texts, which pin the token-join and cooked-string-text semantics); full AST
parity lands with the CFG port, where the differential oracle diffs the
canonical JSON seam end to end.

Run:  python tests/test_syntax_fixtures.py            (verify)
      python tests/test_syntax_fixtures.py --write    (regenerate)
      python tests/run_tests.py                       (runs it as part of the suite)
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang import ast_nodes as A
from ownlang.lexer import LexError
from ownlang.parser import ParseError, parse

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "syntax_parity.json")

_FULL_MODULE = """\
module Demo

lifetime App;
lifetime Window < App;

policy Fast {
  inline_bytes = 256;
  clear_on_release = true;
  fallback = pool;
  trace = false;
  inline_bytes = 128;
}

resource Buffer {
  acquire rent
  release give
  emit_type "byte[]"
  emit_acquire "ArrayPool<byte>.Shared.Rent({args})"
  emit_release "ArrayPool<byte>.Shared.Return({0})"
  emit_borrow "{0}.AsSpan()"
  kind "pooled array"
}

resource Conn {
  acquire open
  release close
}

extern fn Fill(borrow_mut Buffer);
extern fn Hash(borrow Buffer);
extern fn Store(consume Buffer) -> int;
extern fn Mk() -> Buffer;

fn setup(bus: EventBus lifetime App, n: int) -> &mut Buffer lifetime Window {
  // comments vanish in the token stream
  let a = acquire Buffer(n, 2);
  let b = Buffer.scratch(64, policy = Fast, clear = true, clear = false);
  let c = move a;
  borrow c as view {
    use view;
  }
  borrow_mut c as mv {
    Fill(mv);
  }
  if (n < 10) {
    release c;
  } else {
    Store(c);
  }
  while (n) {
    use b;
  }
  subscribe self to bus;
  overspan b;
  release b;
  return c;
}

fn empty() { return; }
"""

_CONDS_MODULE = """\
module m
fn f(a: int) {
  if (a ( b ) "s t" 3) {
    use a;
  } else {
    use a;
  }
  while (a < (3)) {
    use a;
  }
}
"""

# (name, source) — outcomes are computed by running the real parser, never
# hand-written. Every ParseError/LexError message in ownlang/{lexer,parser}.py
# should have at least one case; the repr paths (single quote, double quote,
# backslash, \xNN control) each have one.
CASES: list[tuple[str, str]] = [
    ("full_module", _FULL_MODULE),
    ("minimal_module", "module m"),
    ("cond_token_join", _CONDS_MODULE),
    # Cyrillic on purpose: pins unicode identifiers + char-based columns.
    ("unicode_idents", "module м\nfn f(х: int) {\n  use х;\n}\n"),  # noqa: RUF001
    ("empty_source", ""),
    ("module_without_name", "module"),
    ("not_a_module", "fn f() {}"),
    ("unexpected_char", "@"),
    ("unexpected_char_backslash", "module m \\"),
    ("unexpected_char_control", "module m \x01"),
    ("unexpected_char_after_unicode", "module m\nfn f() { let ф = @; }"),
    ("unterminated_string", 'module m resource R { emit_type "oops'),
    ("rejected_keyword_top_level", "module m for"),
    ("rejected_keyword_in_block", "module m fn f() { loop }"),
    ("bad_top_level_item", "module m junk"),
    ("string_repr_double_quote_path", 'module m "it\'s"'),
    ("bad_resource_member", "module m resource R { junk }"),
    ("subscribe_not_self", "module m fn f() { subscribe foo to X; }"),
    ("subscribe_not_to", "module m fn f() { subscribe self from X; }"),
    ("buffer_positional_after_named", "module m fn f() { let x = Buffer.scratch(1, 2); }"),
    ("unterminated_if_condition", "module m fn f() { if (x"),
    ("unterminated_while_condition", "module m fn f() { while ((x)"),
    ("statement_expected", "module m fn f() { ; }"),
]


def _stmt_count(stmts: list[A.Stmt]) -> int:
    """Recursive statement count: each statement, plus its nested bodies."""
    n = 0
    for s in stmts:
        n += 1
        if isinstance(s, A.BorrowBlock):
            n += _stmt_count(s.body)
        elif isinstance(s, A.If):
            n += _stmt_count(s.then_body) + _stmt_count(s.else_body)
        elif isinstance(s, A.While):
            n += _stmt_count(s.body)
    return n


def _collect_conds(stmts: list[A.Stmt], out: list[str]) -> None:
    """If/while condition texts, in statement order, recursively."""
    for s in stmts:
        if isinstance(s, A.BorrowBlock):
            _collect_conds(s.body, out)
        elif isinstance(s, A.If):
            out.append(s.cond_text)
            _collect_conds(s.then_body, out)
            _collect_conds(s.else_body, out)
        elif isinstance(s, A.While):
            out.append(s.cond_text)
            _collect_conds(s.body, out)


def _digest(mod: A.Module) -> str:
    """Small structural digest both sides compute identically (see the Rust
    mirror in rust/crates/own-syntax/tests/parity.rs)."""
    fns = ",".join(
        f"{f.name}/{len(f.params)}/{_stmt_count(f.body)}" for f in mod.functions
    )
    conds: list[str] = []
    for f in mod.functions:
        _collect_conds(f.body, conds)
    return (
        f"m={mod.name} r={len(mod.resources)} e={len(mod.externs)}"
        f" f={len(mod.functions)} p={len(mod.policies)} l={len(mod.lifetimes)}"
        f" fns=[{fns}] conds=[{'|'.join(conds)}]"
    )


def build() -> dict[str, object]:
    cases: list[dict[str, str]] = []
    for name, source in CASES:
        try:
            mod = parse(source)
        except (LexError, ParseError) as e:
            cases.append({"name": name, "source": source, "error": str(e)})
        else:
            cases.append({"name": name, "source": source, "digest": _digest(mod)})
    return {
        "comment": (
            "GENERATED by tests/test_syntax_fixtures.py --write; do not edit. "
            "Python (ownlang) is authoritative; rust/crates/own-syntax replays "
            "every case and must match byte-for-byte."
        ),
        "cases": cases,
    }


def _render(data: dict[str, object]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def run() -> int:
    expected = _render(build())
    if not os.path.exists(FIXTURE):
        print(f"FAIL: {FIXTURE} missing; regenerate with "
              f"'python tests/test_syntax_fixtures.py --write'")
        return 1
    with open(FIXTURE, encoding="utf-8") as f:
        actual = f.read()
    if actual != expected:
        print(f"FAIL: {FIXTURE} is stale (CASES or the parser changed); "
              f"regenerate with 'python tests/test_syntax_fixtures.py --write' "
              f"and re-run the Rust side (cd rust && cargo test)")
        return 1
    n_err = sum(1 for _, src in CASES if _is_error(src))
    print(f"syntax parity fixtures OK: {len(CASES)} cases "
          f"({n_err} rejections, {len(CASES) - n_err} accepts) verified in sync")
    return 0


def _is_error(source: str) -> bool:
    try:
        parse(source)
    except (LexError, ParseError):
        return True
    return False


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        with open(FIXTURE, "w", encoding="utf-8") as f:
            f.write(_render(build()))
        print(f"wrote {FIXTURE}")
        raise SystemExit(0)
    raise SystemExit(run())
