#!/usr/bin/env python3
"""Shared CFG parity fixtures (P-022 migration step 3) — Python side.

The Rust `own-cfg` crate lowers the `own-syntax` AST to a CFG and projects the
**canonical CFG-JSON seam** (`ownlang.cfg_json`). That seam is the frozen
contract the differential oracle diffs: for every `.own` input the Rust
`canonical_json` must be **byte-identical** to
`python -m ownlang cfg --format json`, and the build-time resolver diagnostics
(by code + line) must match. Copy-pasted expectations rot, so both sides assert
the same corpus: `tests/fixtures/cfg_parity.json`.

* Python is authoritative: `python tests/test_cfg_fixtures.py --write`
  regenerates the file by *running* the real lowering over the whole corpus
  (`corpus/`, `examples/`, `tests/fixtures/`) plus a handful of curated cases;
  this test (`run()`) fails if the committed file is stale.
* Rust replays it: `rust/crates/own-cfg/tests/parity.rs` parses each source,
  lowers it, and asserts the same canonical JSON, the same `(line, code)`
  diagnostics, or — for a rejected source — the same parser error text.

The diagnostics are compared on **code + line only**: the CFG-JSON seam does not
carry diagnostic message text (a verdict-layer contract pinned later by the
SARIF oracle), and `own-cfg` deliberately emits only code + line at this step.

Run:  python tests/test_cfg_fixtures.py            (verify)
      python tests/test_cfg_fixtures.py --write    (regenerate)
      python tests/run_tests.py                    (runs it as part of the suite)
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.cfg import build_cfg, collect_kinds, collect_policies, collect_signatures
from ownlang.cfg_json import canonical_json
from ownlang.lexer import LexError
from ownlang.parser import ParseError, parse

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "cfg_parity.json")

# Directories swept for `.own` inputs, exactly the corpus the issue names.
CORPUS_DIRS = ["corpus", "examples", os.path.join("tests", "fixtures")]

# Curated cases exercising shapes the corpus files don't (a policy-referencing
# buffer, every return-mismatch branch, an unknown/arity-mismatch call, a
# borrow+if+while mix) — outcomes are computed by running the real lowering,
# never hand-written.
_PRELUDE = (
    "module M\n"
    "resource Conn { acquire open release close }\n"
    'resource Token { acquire mint release burn kind "subscription token" }\n'
    "extern fn Fill(borrow_mut Conn);\n"
    "extern fn Hash(borrow Conn);\n"
    "extern fn Store(consume Conn);\n"
)

_CURATED: list[tuple[str, str]] = [
    (
        "curated_full_flow",
        _PRELUDE
        + "fn f(n: int) {\n"
        "    let c = acquire Conn(1);\n"
        "    if (n) {\n"
        "        borrow c as r { use r; }\n"
        "    }\n"
        "    let d = move c;\n"
        "    Store(d);\n"
        "    return;\n"
        "}\n"
        "fn g(n: int) {\n"
        "    let b = Buffer.scratch(n);\n"
        "    release b;\n"
        "}\n",
    ),
    (
        "curated_buffer_policy",
        "module M\n"
        "policy Fast {\n"
        "  inline_bytes = 256;\n"
        "  clear_on_release = true;\n"
        "  fallback = pool;\n"
        "  trace = debug;\n"
        "  counters = true;\n"
        "}\n"
        "fn f(n: int) {\n"
        "  let a = Buffer.scratch(64, policy = Fast, clear = true);\n"
        "  let b = Buffer.stack(size, max = 1024);\n"
        "  let c = Buffer.inline(32);\n"
        "  let d = Buffer.pooled(n);\n"
        "  let e = Buffer.native(n);\n"
        "  release a; release b; release c; release d; release e;\n"
        "}\n",
    ),
    (
        "curated_return_variants",
        "module M\n"
        "resource Conn { acquire open release close }\n"
        "resource Other { acquire open release close }\n"
        "fn ret_owned() -> Conn { let c = acquire Conn(1); return c; }\n"
        "fn ret_borrow(x: &Conn) -> Conn { return x; }\n"
        "fn ret_plain() -> Conn { let n = 3; return n; }\n"
        "fn ret_wrong() -> Conn { let o = acquire Other(1); return o; }\n"
        "fn ret_void_val() { let c = acquire Conn(1); return c; }\n"
        "fn ret_missing() -> Conn { }\n",
    ),
    (
        "curated_call_errors",
        "module M\n"
        "resource Conn { acquire open release close }\n"
        "extern fn Need(consume Conn);\n"
        "fn f() {\n"
        "  let c = acquire Conn(1);\n"
        "  Unknown(c);\n"
        "  Need(c, c);\n"
        "  Need(c);\n"
        "}\n",
    ),
    (
        "curated_loops_and_borrows",
        "module M\n"
        "resource Conn { acquire open release close }\n"
        "extern fn Fill(borrow_mut Conn);\n"
        "fn f(n: int) {\n"
        "  let c = acquire Conn(1);\n"
        "  while (n) {\n"
        "    borrow_mut c as m { Fill(m); }\n"
        "    use c;\n"
        "  }\n"
        "  overspan c;\n"
        "  release c;\n"
        "}\n",
    ),
    (
        "curated_resolver_errors",
        "module M\n"
        "resource Conn { acquire open release close }\n"
        "fn f() {\n"
        "  use undef;\n"
        "  let a = acquire Missing(1);\n"
        "  let b = acquire Conn(1);\n"
        "  let b = acquire Conn(2);\n"
        "  release b;\n"
        "  let c = b;\n"
        "}\n",
    ),
]


def _corpus_files() -> list[str]:
    """Every `.own` file under the swept directories, as repo-relative POSIX
    paths, sorted — a stable, platform-independent case ordering."""
    found: list[str] = []
    for base in CORPUS_DIRS:
        root = os.path.join(REPO_ROOT, base)
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                if name.endswith(".own"):
                    rel = os.path.relpath(os.path.join(dirpath, name), REPO_ROOT)
                    found.append(rel.replace(os.sep, "/"))
    return sorted(found)


def _lower(mod: object) -> tuple[str, list[list[object]]]:
    """Mirror `cmd_cfg`'s loop: the canonical CFG JSON plus the concatenated
    build-time diagnostics as `[line, code]` pairs, in emission order."""
    rnames = {r.name for r in mod.resources}  # type: ignore[attr-defined]
    sigs = collect_signatures(mod)  # type: ignore[arg-type]
    pols = collect_policies(mod)  # type: ignore[arg-type]
    kinds = collect_kinds(mod)  # type: ignore[arg-type]
    cfgs = []
    diags: list[list[object]] = []
    for fn in mod.functions:  # type: ignore[attr-defined]
        cfg, d = build_cfg(fn, rnames, sigs, pols, kinds)
        cfgs.append(cfg)
        diags.extend([dg.line, dg.code] for dg in d)
    return canonical_json(cfgs), diags


def _case(name: str, source: str) -> dict[str, object]:
    try:
        mod = parse(source)
    except (LexError, ParseError) as e:
        return {"name": name, "source": source, "error": str(e)}
    cfg_str, diags = _lower(mod)
    return {"name": name, "source": source, "cfg": cfg_str, "diags": diags}


def build() -> dict[str, object]:
    cases: list[dict[str, object]] = []
    for rel in _corpus_files():
        with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as f:
            cases.append(_case(rel, f.read()))
    for name, source in _CURATED:
        cases.append(_case(name, source))
    return {
        "comment": (
            "GENERATED by tests/test_cfg_fixtures.py --write; do not edit. "
            "Python (ownlang) is authoritative; rust/crates/own-cfg replays "
            "every case and must match the canonical CFG JSON byte-for-byte "
            "and the (line, code) diagnostics exactly."
        ),
        "cases": cases,
    }


def _render(data: dict[str, object]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def run() -> int:
    expected = _render(build())
    if not os.path.exists(FIXTURE):
        print(f"FAIL: {FIXTURE} missing; regenerate with "
              f"'python tests/test_cfg_fixtures.py --write'")
        return 1
    with open(FIXTURE, encoding="utf-8") as f:
        actual = f.read()
    if actual != expected:
        print(f"FAIL: {FIXTURE} is stale (the corpus or the lowering changed); "
              f"regenerate with 'python tests/test_cfg_fixtures.py --write' and "
              f"re-run the Rust side (cd rust && cargo test)")
        return 1
    data = json.loads(actual)
    cases = data["cases"]
    n_err = sum(1 for c in cases if "error" in c)
    print(f"CFG parity fixtures OK: {len(cases)} cases "
          f"({n_err} rejections, {len(cases) - n_err} lowerings) verified in sync")
    return 0


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
        with open(FIXTURE, "w", encoding="utf-8") as f:
            f.write(_render(build()))
        print(f"wrote {FIXTURE}")
        raise SystemExit(0)
    raise SystemExit(run())
