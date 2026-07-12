#!/usr/bin/env python3
"""Shared diagnostics parity fixtures (P-022 migration step 4, issue #214) — Python side.

The Rust `own-analysis` crate (once ported) parses `.own` source with
`own-syntax`, lowers it with `own-cfg`, runs the worklist solver + the ownership
/ lifetime analyses, and constructs `own-diagnostics` verdicts. This fixture is
the **frozen `(path, line, code)` contract** the differential oracle diffs: for
every `.own` input the Rust `check` surface must emit the same ordered list of
`[line, code]` pairs Python's `check` surface does — including intra-location
(same-line, same-code) ordering, which the list position pins.

Copy-pasted expectations rot, so both sides assert the same corpus:
`tests/fixtures/diag_parity.json`. This mirrors the #203 CFG-parity ratchet
(`tests/test_cfg_fixtures.py`), one layer up: CFG-parity froze `(line, code)`
*resolver* diagnostics at the lowering seam; this freezes the full **verdict**
`(line, code)` set at the `check` seam.

Scope of this seam (checkpoint 1, before the semantic port):

* The compared surface is the `check` command's diagnostics — exactly
  `ownlang.__main__._collect`: parse (`own-syntax`), and on a lex/parse error
  emit a single synthetic **OWN020** at the error line (a preserved Python
  quirk — a *syntax* error is reported under the "unsupported construct" code;
  see the checkpoint-1 note); otherwise run `check_module` (buffer-policy
  validation + `check_lifetimes` + per-function `analyze`), whose result is
  already sorted by `(line, code)` with a stable tie order.
* This exercises **ownership**, **lifetime/region**, and **buffer-policy**
  diagnostics — every family `check_module` produces. The **effects (EFF*)**
  and **DI (DI*)** families are *sidecar analyses the OwnIR bridge routes facts
  to* (`ownlang/ownir.py::check_facts`), not the `.own` core lattice, so no
  `.own` input exercises them; their parity needs OwnIR **fact** fixtures and
  lands with `own-bridge` (migration step 6), not here. Message text, evidence
  slices and SARIF are later steps (5) and deliberately NOT frozen here.

Compared on **code + line only**, per input, in emission order.

Run:  python tests/test_diag_fixtures.py            (verify)
      python tests/test_diag_fixtures.py --write    (regenerate)
      python tests/run_tests.py                     (runs it as part of the suite)
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.__main__ import _collect

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "diag_parity.json")

# Directories swept for `.own` inputs — the same corpus #214 names and the CFG
# ratchet already sweeps (`tests/test_cfg_fixtures.py`), so the two seams stay
# on identical inputs.
CORPUS_DIRS = ["corpus", "examples", os.path.join("tests", "fixtures")]

# Curated cases exercising verdict shapes as concentrated single files (a leak,
# use-after-release, double-release, use-after-move, an escape/lifetime promotion,
# a buffer-policy violation, and the OWN020 parse-error quirk). Outcomes are
# COMPUTED by running the real `check` surface, never hand-written — a curated
# case pins a shape, it does not assert a guessed verdict.
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
        "curated_leak_and_release",
        _PRELUDE
        + "fn leaks() {\n"
        "    let c = acquire Conn(1);\n"
        "    return;\n"
        "}\n"
        "fn clean() {\n"
        "    let c = acquire Conn(1);\n"
        "    release c;\n"
        "    return;\n"
        "}\n",
    ),
    (
        "curated_use_after_release",
        _PRELUDE
        + "fn f() {\n"
        "    let c = acquire Conn(1);\n"
        "    release c;\n"
        "    Hash(c);\n"
        "    return;\n"
        "}\n",
    ),
    (
        "curated_double_release",
        _PRELUDE
        + "fn f() {\n"
        "    let c = acquire Conn(1);\n"
        "    release c;\n"
        "    release c;\n"
        "    return;\n"
        "}\n",
    ),
    (
        "curated_use_after_move",
        _PRELUDE
        + "fn f() {\n"
        "    let c = acquire Conn(1);\n"
        "    let d = move c;\n"
        "    Hash(c);\n"
        "    Store(d);\n"
        "    return;\n"
        "}\n",
    ),
    (
        "curated_maybe_release_branch",
        _PRELUDE
        + "fn f(n: int) {\n"
        "    let c = acquire Conn(1);\n"
        "    if (n) { release c; }\n"
        "    Hash(c);\n"
        "    return;\n"
        "}\n",
    ),
    (
        "curated_buffer_policy",
        "module M\n"
        "fn f(n: int) {\n"
        "  let a = Buffer.inline(999999);\n"
        "  release a;\n"
        "}\n",
    ),
    (
        "curated_parse_error_is_own020",
        "module M\nfn f( {\n",
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


def _diags_for(source: str) -> list[list[object]]:
    """The `check` surface's ordered `[line, code]` verdict list for one source.

    `_collect` is the exact function `python -m ownlang check` runs: it wraps a
    lex/parse failure as a single synthetic OWN020 and otherwise returns
    `check_module`'s diagnostics, already sorted by `(line, code)` with a stable
    intra-tie order. We freeze that order verbatim — list position is the
    deterministic intra-location ordering the oracle pins."""
    diags, _mod = _collect(source)
    return [[d.line, d.code] for d in diags]


def _case(name: str, source: str) -> dict[str, object]:
    return {"name": name, "source": source, "diags": _diags_for(source)}


def build() -> dict[str, object]:
    cases: list[dict[str, object]] = []
    for rel in _corpus_files():
        with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as f:
            cases.append(_case(rel, f.read()))
    for name, source in _CURATED:
        cases.append(_case(name, source))
    return {
        "comment": (
            "GENERATED by tests/test_diag_fixtures.py --write; do not edit. "
            "Python (ownlang) is authoritative; rust/crates/own-analysis replays "
            "every case through the `check` surface and must match the ordered "
            "(line, code) verdict list exactly (issue #214, P-022 step 4)."
        ),
        "cases": cases,
    }


def _render(data: dict[str, object]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def run() -> int:
    expected = _render(build())
    if not os.path.exists(FIXTURE):
        print(f"FAIL: {FIXTURE} missing; regenerate with "
              f"'python tests/test_diag_fixtures.py --write'")
        return 1
    with open(FIXTURE, encoding="utf-8") as f:
        actual = f.read()
    if actual != expected:
        print(f"FAIL: {FIXTURE} is stale (the corpus or the checker changed); "
              f"regenerate with 'python tests/test_diag_fixtures.py --write' and "
              f"re-run the Rust side (cd rust && cargo test)")
        return 1
    data = json.loads(actual)
    cases = data["cases"]
    n_findings = sum(len(c["diags"]) for c in cases)
    n_flagged = sum(1 for c in cases if c["diags"])
    print(f"diagnostics parity fixtures OK: {len(cases)} cases "
          f"({n_flagged} with findings, {n_findings} total (line, code) pairs) "
          f"verified in sync")
    return 0


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
        with open(FIXTURE, "w", encoding="utf-8") as f:
            f.write(_render(build()))
        print(f"wrote {FIXTURE}")
        raise SystemExit(0)
    raise SystemExit(run())
