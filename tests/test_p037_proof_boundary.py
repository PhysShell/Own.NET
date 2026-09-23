#!/usr/bin/env python3
"""P-037 Phase B: adversarial self-tests for scripts/p037_proof_boundary.py.

The audit passing on the current tree is not, by itself, evidence the audit
would refuse a broken one. This file proves the refusal side: it builds a
small, self-consistent fixture tree (two harnesses, one assume, matching
ledgers), confirms the audit reports it clean, then corrupts exactly one
thing per test and asserts the audit reports exactly the corresponding
failure -- never a false green.

Every test patches the module's own path/file-list constants to point at a
temporary tree; none of it reads or writes the real formal/p037-kernel/ or
docs/evidence/p037-b-ledger-*.json.

A final section tests pb._mask_non_code directly, as scanner unit tests
rather than fixture-tree corruptions: real kani::assume(...) call sites
(plain, whitespace-split, comment-interrupted) must survive masking; the
same text in a line comment, a block comment (nested or not), a normal
string or a raw string must not; an unterminated comment or raw string
must refuse rather than guess.

Run:  python tests/test_p037_proof_boundary.py
      python tests/run_tests.py             (in the suite)
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import p037_proof_boundary as pb

_failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global _failures
    if ok:
        print(f"ok[{name}]")
    else:
        _failures += 1
        print(f"FAIL[{name}]: {detail}")


SAMPLE_RS = """#[cfg(kani)]
mod proofs {
    #[kani::proof]
    fn sample_fast_harness() {
        let x: bool = kani::any();
        kani::assume(x);
        assert!(x);
    }

    #[kani::proof]
    fn sample_heavy_harness() {
        assert!(true);
    }
}
"""

FAST_CI_YML = """jobs:
  formal-p037:
    steps:
      - run: |
          for h in \\
            sample_fast_harness; do
            cargo kani --harness "$h"
          done
"""

HEAVY_CI_YML = """jobs:
  heavy-kani:
    steps:
      - run: |
          for h in \\
            sample_heavy_harness; do
            cargo kani --harness "$h"
          done
"""


@contextlib.contextmanager
def _patched(**kwargs: Any) -> Iterator[None]:
    saved = {k: getattr(pb, k) for k in kwargs}
    for k, v in kwargs.items():
        setattr(pb, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(pb, k, v)


def _build_clean_tree(root: Path) -> None:
    """Write the fixture source + CI files, then derive-and-write ledgers
    that exactly match what the module's own scanners find in them --
    the baseline is clean by construction, not by hand-counted line numbers."""
    properties = root / "properties"
    properties.mkdir(parents=True, exist_ok=True)
    (properties / "sample.rs").write_text(SAMPLE_RS, encoding="utf-8")
    (root / "ci.yml").write_text(FAST_CI_YML, encoding="utf-8")
    (root / "formal-p037-gate.yml").write_text(HEAVY_CI_YML, encoding="utf-8")

    with _patched(PROPERTIES_DIR=properties, HARNESS_FILES=("sample.rs",),
                  ASSUME_FILES=("sample.rs",)):
        harnesses = pb.derive_source_harnesses()
        assumes = pb.derive_source_assumes()

    harness_ledger = {
        "harnesses": [
            {"harness": name, "claim": "test claim", "production_subject": "test subject"}
            for name in harnesses
        ]
    }
    assumption_ledger = {
        "assumptions": [
            {
                **a,
                "disposition": "PRODUCTION_GUARANTOR",
                "guarantor": "test guarantor",
                "non_vacuity_witness": "test witness",
                "non_vacuity_status": "witnessed",
            }
            for a in assumes
        ]
    }
    (root / "harnesses.json").write_text(json.dumps(harness_ledger), encoding="utf-8")
    (root / "assumptions.json").write_text(json.dumps(assumption_ledger), encoding="utf-8")


@contextlib.contextmanager
def _clean_tree() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="p037-proof-boundary-test-") as tmp:
        root = Path(tmp)
        _build_clean_tree(root)
        with _patched(
            PROPERTIES_DIR=root / "properties",
            HARNESS_FILES=("sample.rs",),
            ASSUME_FILES=("sample.rs",),
            CI_FAST_FILE=root / "ci.yml",
            CI_HEAVY_FILE=root / "formal-p037-gate.yml",
            HARNESS_LEDGER=root / "harnesses.json",
            ASSUMPTION_LEDGER=root / "assumptions.json",
        ):
            yield root


def _rewrite_json(path: Path, mutate) -> None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    mutate(doc)
    path.write_text(json.dumps(doc), encoding="utf-8")


def run() -> int:
    # 0. sanity: the unmodified fixture tree is clean.
    with _clean_tree():
        problems, summary = pb.run()
        check("baseline-fixture-is-clean", not problems, f"{problems}")
        clean_counts = summary["source_harnesses"] == 2 and summary["assumptions_total"] == 1
        check("baseline-counts", clean_counts, f"{summary}")

    # 1. a source harness disappears from both CI sets.
    with _clean_tree() as root:
        renamed = FAST_CI_YML.replace("sample_fast_harness", "renamed_elsewhere")
        (root / "ci.yml").write_text(renamed, encoding="utf-8")
        problems, _ = pb.run()
        check("red-harness-missing-from-both-ci-sets",
              any("neither CI set" in p and "sample_fast_harness" in p for p in problems),
              f"{problems}")

    # 2. a harness is listed in both fast and heavy.
    with _clean_tree() as root:
        (root / "formal-p037-gate.yml").write_text(
            HEAVY_CI_YML.replace("sample_heavy_harness", "sample_fast_harness"), encoding="utf-8")
        problems, _ = pb.run()
        check("red-harness-in-both-fast-and-heavy",
              any("not disjoint" in p and "sample_fast_harness" in p for p in problems),
              f"{problems}")

    # 3. CI names a nonexistent harness.
    with _clean_tree() as root:
        (root / "ci.yml").write_text(
            FAST_CI_YML.replace("sample_fast_harness; do", "sample_fast_harness ghost_harness; do"),
            encoding="utf-8")
        problems, _ = pb.run()
        check("red-ci-names-nonexistent-harness",
              any("absent from source" in p and "ghost_harness" in p for p in problems),
              f"{problems}")

    # 4. a source harness has no ledger row.
    with _clean_tree() as root:
        _rewrite_json(root / "harnesses.json",
                      lambda d: d["harnesses"].pop())  # drop one of the two rows
        problems, _ = pb.run()
        check("red-source-harness-with-no-ledger-row",
              any("no ledger row" in p for p in problems), f"{problems}")

    # 5. a ledger row names no source harness.
    with _clean_tree() as root:
        _rewrite_json(root / "harnesses.json",
                      lambda d: d["harnesses"].append(
                          {"harness": "phantom_harness", "claim": "x", "production_subject": "y"}))
        problems, _ = pb.run()
        check("red-ledger-row-naming-no-source-harness",
              any("naming no source harness" in p and "phantom_harness" in p for p in problems),
              f"{problems}")

    # 6. a load-bearing kani::assume has no disposition.
    with _clean_tree() as root:
        _rewrite_json(root / "assumptions.json",
                      lambda d: d["assumptions"][0].__setitem__("disposition", None))
        problems, _ = pb.run()
        check("red-assume-with-no-disposition",
              any("no valid disposition" in p for p in problems), f"{problems}")

    # 7. a PRODUCTION_GUARANTOR entry lacks a concrete guarantor.
    with _clean_tree() as root:
        _rewrite_json(root / "assumptions.json",
                      lambda d: d["assumptions"][0].__setitem__("guarantor", ""))
        problems, _ = pb.run()
        check("red-production-guarantor-without-a-guarantor",
              any("names no concrete guarantor" in p for p in problems), f"{problems}")

    # 8. an OUTSIDE_KANI_BOUNDARY entry lacks an explicit residual obligation.
    with _clean_tree() as root:
        def _to_outside_no_residual(d: dict[str, Any]) -> None:
            row = d["assumptions"][0]
            row["disposition"] = "OUTSIDE_KANI_BOUNDARY"
            row["reason"] = "some reason"
            row.pop("residual_production_obligation", None)
        _rewrite_json(root / "assumptions.json", _to_outside_no_residual)
        problems, _ = pb.run()
        check("red-outside-boundary-without-residual-obligation",
              any("lacks a reason" in p or "residual_production_obligation" in p for p in problems),
              f"{problems}")

    # 9. a load-bearing restriction has no non-vacuity witness.
    with _clean_tree() as root:
        _rewrite_json(root / "assumptions.json",
                      lambda d: d["assumptions"][0].__setitem__("non_vacuity_status", "gap"))
        problems, _ = pb.run()
        check("red-restriction-with-no-non-vacuity-witness",
              any("no complete non-vacuity witness" in p for p in problems), f"{problems}")

    # Bonus: an orphan assumption ledger row (naming no source site) is also refused.
    with _clean_tree() as root:
        _rewrite_json(root / "assumptions.json",
                      lambda d: d["assumptions"].append({
                          "file": "properties/sample.rs", "line": 999, "expression": "ghost",
                          "disposition": "PRODUCTION_GUARANTOR", "guarantor": "g",
                          "non_vacuity_witness": "w", "non_vacuity_status": "witnessed"}))
        problems, _ = pb.run()
        check("red-orphan-assumption-ledger-row",
              any("naming no source site" in p for p in problems), f"{problems}")

    # Ambiguous-structure refusals (REFUSED, distinct from a RED finding).
    with _clean_tree() as root:
        text = (root / "properties" / "sample.rs").read_text(encoding="utf-8")
        broken = text.replace("#[kani::proof]\n    fn sample_heavy_harness() {",
                              "#[kani::proof]\n    // a comment, not a fn or another attribute\n"
                              "    fn sample_heavy_harness() {")
        (root / "properties" / "sample.rs").write_text(broken, encoding="utf-8")
        try:
            pb.run()
            check("refused-on-unrecognized-shape-after-proof-attr", False, "did not raise Refused")
        except pb.Refused:
            check("refused-on-unrecognized-shape-after-proof-attr", True)

    with _clean_tree() as root:
        text = (root / "properties" / "sample.rs").read_text(encoding="utf-8")
        broken = text.replace("kani::assume(x);", "kani::assume(x;")  # drops the closing paren
        (root / "properties" / "sample.rs").write_text(broken, encoding="utf-8")
        try:
            pb.run()
            check("refused-on-unbalanced-assume-parens", False, "did not raise Refused")
        except pb.Refused:
            check("refused-on-unbalanced-assume-parens", True)

    with _clean_tree() as root:
        (root / "ci.yml").write_text("jobs:\n  formal-p037:\n    steps: []\n", encoding="utf-8")
        try:
            pb.run()
            check("refused-on-missing-for-h-loop", False, "did not raise Refused")
        except pb.Refused:
            check("refused-on-missing-for-h-loop", True)

    # Lexical masking (owner ruling, 2026-09-23): a comment naming
    # kani::assume(...) in prose must never read as a call site -- the
    # incident that prompted this section was exactly that, caught by this
    # audit's own run, not by one of its self-tests. These check
    # pb._mask_non_code directly, as scanner unit tests, not through a full
    # fixture tree.
    def masked_has_assume(src: str) -> bool:
        return bool(pb._ASSUME_TOKEN.search(pb._mask_non_code(src, "lexer-check")))

    real_cases = {
        "plain": "kani::assume(x);",
        "spaced": "kani :: assume (x);",
        "split-across-lines": "kani::\n    assume(x);",
        "comment-mid-tokens": "kani::assume/* why */(x);",  # bonus: a real call,
        # a comment merely interrupting it -- masking turns the comment into
        # whitespace, which \s* already tolerates, so this is found for free.
    }
    for name, src in real_cases.items():
        check(f"lexer-real-{name}", masked_has_assume(src), src)

    ignore_cases = {
        "line-comment": "// kani::assume(x);",
        "block-comment": "/* kani::assume(x); */",
        "nested-block-comment": "/* nested /* kani::assume(x) */ */",
        "normal-string": '"kani::assume(x);"',
        "raw-string": 'r#"kani::assume(x);"#',
    }
    for name, src in ignore_cases.items():
        check(f"lexer-ignore-{name}", not masked_has_assume(src), src)

    lexer_refuse_cases = {
        "unterminated-block-comment": "/* kani::assume(x);",
        "unterminated-raw-string": 'r#"kani::assume(x);"',
    }
    for name, src in lexer_refuse_cases.items():
        try:
            pb._mask_non_code(src, "lexer-check")
            check(f"lexer-refuse-{name}", False, "did not raise Refused")
        except pb.Refused:
            check(f"lexer-refuse-{name}", True)

    # Char literals and lifetimes were on the owner's exclusion list but not
    # in the named selftest set; the two real risks are a char literal in an
    # assume's own argument swallowing surrounding code, and a lifetime
    # (which starts with the same `'` a char literal does) being mistaken
    # for an unterminated char literal and wrongly refused.
    check("lexer-real-char-literal-in-argument",
          masked_has_assume("kani::assume('a' == c);"),
          "a char literal inside the argument must not hide the call")
    try:
        found = masked_has_assume("fn f<'a>(x: &'a bool) { kani::assume(*x); }")
        check("lexer-real-lifetime-not-a-char-literal", found,
              "a lifetime must not be refused as an unterminated char literal")
    except pb.Refused as exc:
        check("lexer-real-lifetime-not-a-char-literal", False, f"wrongly refused: {exc}")

    if _failures:
        print(f"RESULT: {_failures} check(s) failed")
        return 1
    print("RESULT: the proof-boundary audit refuses every corrupted fixture it was shown, "
          "and only those")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
