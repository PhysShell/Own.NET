#!/usr/bin/env python3
"""Structured diagnostic-model parity fixtures (P-022 step 5a, issue #255) — Python side.

`tests/test_diag_fixtures.py` froze the **verdict set** at the `check` seam, but
only as `(line, code)` pairs: everything that distinguishes two findings sharing
an anchor — subject, resource kind, severity, the ordered evidence slice — is
collapsed there by construction. That was correct for step 4 (it pinned *which*
verdicts fire); it is not enough for step 5a, whose whole point is the rest of
the record.

This fixture freezes the **structural identity** of a diagnostic: the full
`ownlang.diagnostics.Diagnostic` field set plus the primary-location identity the
dataclass does not itself carry. The Rust `own-diagnostics` crate replays it with
zero Python and must agree on which records are the *same* finding and which are
*different* ones.

Slice boundary (PR 1 of three for #255):

* **In scope** — the data model, the primary-location envelope, and a canonical
  comparison identity that does not collapse distinct diagnostics.
* **Out of scope** — canonical *message text* and the total ordering contract
  (PR 2), and the full OWN/DI/EFF corpus ledger (PR 3). The `message` field is
  carried here verbatim as an opaque string so the schema is final now and PR 2
  can assert rendering *into* it without reshaping this file.

Why the records are hand-authored rather than swept from the corpus: the
controls this slice needs (two findings identical but for `subject`, an evidence
slice reordered, a non-ASCII path) are *identity* shapes, and the corpus does not
reliably contain them. They are still Python-authored in the strict sense that
matters — every record is a real `Diagnostic`/`Evidence` instance built by
`ownlang`, so field defaults, the `__post_init__` code guard and frozen-dataclass
equality all come from the reference implementation, never from a hand-written
JSON literal. `distinct_records` below is computed by Python's own dataclass
equality; Rust must reproduce that count from its comparison key. The corpus
sweep arrives in PR 3, where it belongs.

## Location envelope — the load-bearing schema decision

`ownlang.diagnostics.Diagnostic` has **no `path` and no `column`**:

* `path` is the *input identity* — the core reports per-file and the caller knows
  which file it handed over (that is why the step-4 oracle surface is written
  `(path, line, code)` while the frozen pair is `(line, code)`);
* `column` lives on `ownlang.ownir.Finding` (#317), is optional, and is
  explicitly *never substituted* — the renderer's `Diagnostic._caret_col` is a
  display heuristic recovered by re-reading the source line, not a source column,
  and must not be confused for one.

So this schema wraps the ported dataclass in a `{path, column, diagnostic}`
envelope instead of adding two fields to it. Adding them to `Diagnostic` would
make the Rust type stop mirroring the Python one to suit a fixture — the exact
"do not change the reference to simplify the port" rule #255 forbids.

Paths are carried **verbatim**: `src\\A.cs` and `src/A.cs` are two distinct
records here, not one. Python normalises separators only at the SARIF seam
(`ownlang.evidence._phys`), so normalising in the identity would invent a
behaviour the reference does not have at this layer. The SARIF projection owns
that, in #256.

Run:  python tests/test_diag_model_fixtures.py            (verify)
      python tests/test_diag_model_fixtures.py --write    (regenerate)
      python tests/run_tests.py                           (runs it as part of the suite)
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.diagnostics import Diagnostic, Evidence, Severity

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "diag_model.json")

# The schema this slice freezes. PR 2 (rendering/ordering) and PR 3 (the full
# corpus ledger) ADD cases; neither may reshape a record, so this stays 1 unless
# the envelope itself changes -- which would be a reviewed schema decision.
SCHEMA_VERSION = 1


def _d(code: str, message: str, line: int, **kw: object) -> Diagnostic:
    """A real `Diagnostic`, so defaults and the unknown-code guard are the
    reference's, not this file's."""
    return Diagnostic(code=code, message=message, line=line, **kw)  # type: ignore[arg-type]


# Non-ASCII controls, hoisted to one literal per line so a confusable-character
# lint stays reviewable at the exact string it fires on. The two Cyrillic paths
# below differ by a single letter (U+0451 YO vs U+0435 IE) -- visually all but
# identical, and they must stay two records. Naming them YO/YE keeps that the
# point of the case rather than a typo a reviewer would "fix".
_RU_PATH_YO = "src/Отчёт.cs"
_RU_PATH_YE = "src/Отчет.cs"
# Kept deliberately: every letter of the first word is Latin-confusable, so it
# reads as "pecypc" to a homoglyph attack. That is a real identity hazard, which
# is why it belongs in the fixture rather than being softened away.
_RU_MESSAGE = "ресурс не освобождён"  # noqa: RUF001
_RU_SUBJECT = "поток#5"
_RU_KIND = "подписка"
_RU_LABEL = "получен здесь"
_JA_PATH = "src/報告.cs"
_JA_MESSAGE = "リソースが解放されていません"
_JA_SUBJECT = "ストリーム#5"
_JA_LABEL = "取得"


# Each case: a name, why it exists, and the records whose pairwise identity is
# the thing under test. Records within a case are deliberately near-identical --
# a key that collapses any pair fails the case.
_CASES: list[tuple[str, str, list[tuple[str, int | None, Diagnostic]]]] = [
    (
        "distinct_subject_at_one_anchor",
        "same (path, line, code) and message; only `subject` differs -- the step-4 "
        "(line, code) key collapses these two into one finding, which is exactly "
        "the loss this slice repairs",
        [
            ("src/Grid.cs", None, _d("OWN001", "resource not released", 42,
                                     subject="reader#42")),
            ("src/Grid.cs", None, _d("OWN001", "resource not released", 42,
                                     subject="writer#42")),
        ],
    ),
    (
        "distinct_resource_kind_at_one_anchor",
        "same anchor and subject; only the `[resource: ...]` kind differs -- the "
        "domain-neutral tag a profile keys off, so it must not be identity-blind",
        [
            ("src/Grid.cs", None, _d("OWN001", "resource not released", 42,
                                     subject="t#42", resource_kind="subscription token")),
            ("src/Grid.cs", None, _d("OWN001", "resource not released", 42,
                                     subject="t#42", resource_kind="timer")),
        ],
    ),
    (
        "distinct_severity_at_one_anchor",
        "the P-004 tiering case: the same verdict shown at error vs warning tier "
        "is not the same record",
        [
            ("src/Grid.cs", None, _d("OWN001", "resource not released", 42,
                                     severity=Severity.ERROR)),
            ("src/Grid.cs", None, _d("OWN001", "resource not released", 42,
                                     severity=Severity.WARNING)),
        ],
    ),
    (
        "missing_optional_evidence_and_fields",
        "the sparse record: no subject, no resource kind, no evidence -- the "
        "all-defaults shape, distinct from the same anchor carrying any of them",
        [
            ("src/Sparse.cs", None, _d("OWN003", "double release", 7)),
            ("src/Sparse.cs", None, _d("OWN003", "double release", 7,
                                       subject="c#7")),
            ("src/Sparse.cs", None, _d("OWN003", "double release", 7,
                                       evidence=(Evidence(line=5, label="released here",
                                                          role="released"),))),
        ],
    ),
    (
        "evidence_order_is_significant",
        "identical steps in a different order: the slice is an ORDERED reachability "
        "path, so a key that sorts or sets it would call these equal",
        [
            ("src/Flow.cs", None, _d("OWN014", "value escapes", 30, evidence=(
                Evidence(line=10, label="acquired here", role="acquired"),
                Evidence(line=20, label="escapes here", role="escaped"),
            ))),
            ("src/Flow.cs", None, _d("OWN014", "value escapes", 30, evidence=(
                Evidence(line=20, label="escapes here", role="escaped"),
                Evidence(line=10, label="acquired here", role="acquired"),
            ))),
        ],
    ),
    (
        "evidence_role_and_label_are_identity",
        "same step line, different role or label -- two different explanations of "
        "the same anchor, not one",
        [
            ("src/Flow.cs", None, _d("OWN001", "not released", 30, evidence=(
                Evidence(line=10, label="acquired here", role="acquired"),))),
            ("src/Flow.cs", None, _d("OWN001", "not released", 30, evidence=(
                Evidence(line=10, label="acquired here", role="related"),))),
            ("src/Flow.cs", None, _d("OWN001", "not released", 30, evidence=(
                Evidence(line=10, label="consumed here", role="acquired"),))),
        ],
    ),
    (
        "multi_file_evidence",
        "a cross-file slice: `file=None` means 'the anchor's own file', so the "
        "None form and an explicit same-path form are different records, and a "
        "step in another file is different again",
        [
            ("src/Vm.cs", None, _d("DI001", "captive dependency", 12, evidence=(
                Evidence(line=3, label="registered here", role="related"),))),
            ("src/Vm.cs", None, _d("DI001", "captive dependency", 12, evidence=(
                Evidence(line=3, label="registered here", role="related",
                         file="src/Vm.cs"),))),
            ("src/Vm.cs", None, _d("DI001", "captive dependency", 12, evidence=(
                Evidence(line=3, label="registered here", role="related",
                         file="src/Startup.cs"),))),
        ],
    ),
    (
        "windows_and_unix_path_forms",
        "separator forms are carried verbatim at this layer -- Python normalises "
        "only at the SARIF seam (evidence._phys), so folding them here would "
        "invent a behaviour the reference does not have",
        [
            ("src/A.cs", None, _d("OWN002", "use after release", 9)),
            ("src\\A.cs", None, _d("OWN002", "use after release", 9)),
            ("SRC/A.cs", None, _d("OWN002", "use after release", 9)),
        ],
    ),
    (
        "column_presence_and_value",
        "the #317 source column: optional, never substituted -- absent, 7 and 9 "
        "are three records, and absent must not silently equal any value",
        [
            ("src/Col.cs", None, _d("OWN001", "not released", 15)),
            ("src/Col.cs", 7, _d("OWN001", "not released", 15)),
            ("src/Col.cs", 9, _d("OWN001", "not released", 15)),
        ],
    ),
    (
        "unicode_paths_labels_and_subjects",
        "non-ASCII in every string position the identity spans; Rust must compare "
        "these by content, and the fixture is written with ensure_ascii=False so a "
        "mojibake regression is visible in review",
        [
            (_RU_PATH_YO, None, _d("OWN001", _RU_MESSAGE, 5,
                                   subject=_RU_SUBJECT, resource_kind=_RU_KIND,
                                   evidence=(Evidence(line=2, label=_RU_LABEL,
                                                      role="acquired"),))),
            (_RU_PATH_YE, None, _d("OWN001", _RU_MESSAGE, 5,
                                   subject=_RU_SUBJECT, resource_kind=_RU_KIND,
                                   evidence=(Evidence(line=2, label=_RU_LABEL,
                                                      role="acquired"),))),
            (_JA_PATH, None, _d("OWN001", _JA_MESSAGE, 5,
                                subject=_JA_SUBJECT,
                                evidence=(Evidence(line=2, label=_JA_LABEL,
                                                   role="acquired"),))),
        ],
    ),
    (
        "identical_records_are_one",
        "the negative control: two byte-identical records ARE the same finding. "
        "Without this, a key that hashed object identity would pass every case above",
        [
            ("src/Same.cs", 4, _d("OWN001", "not released", 11, subject="s#11")),
            ("src/Same.cs", 4, _d("OWN001", "not released", 11, subject="s#11")),
        ],
    ),
]


def _evidence_json(ev: Evidence) -> dict[str, object]:
    return {"line": ev.line, "label": ev.label, "file": ev.file, "role": ev.role}


def _diagnostic_json(d: Diagnostic) -> dict[str, object]:
    return {
        "code": d.code,
        "message": d.message,
        "line": d.line,
        "severity": d.severity.value,
        "subject": d.subject,
        "resource_kind": d.resource_kind,
        "evidence": [_evidence_json(e) for e in d.evidence],
    }


def _record_json(path: str, column: int | None, d: Diagnostic) -> dict[str, object]:
    return {"path": path, "column": column, "diagnostic": _diagnostic_json(d)}


def build() -> dict[str, object]:
    cases: list[dict[str, object]] = []
    for name, why, records in _CASES:
        # Python's own frozen-dataclass equality decides how many DISTINCT
        # findings this case holds. Rust must reach the same number from its
        # comparison key -- that equality, not a hand-written count, is the
        # reference behaviour under test.
        distinct = len({(p, c, d) for (p, c, d) in records})
        cases.append({
            "name": name,
            "why": why,
            "records": [_record_json(p, c, d) for (p, c, d) in records],
            "distinct_records": distinct,
        })
    return {
        "comment": (
            "GENERATED by tests/test_diag_model_fixtures.py --write; do not edit. "
            "Python (ownlang) is authoritative. Structural identity of a diagnostic "
            "plus its primary-location envelope (P-022 step 5a, issue #255, PR 1 of 3): "
            "rust/crates/own-diagnostics replays every case with zero Python and must "
            "agree on distinct_records. Message TEXT and the total ordering contract "
            "are PR 2; the full OWN/DI/EFF corpus ledger is PR 3."
        ),
        "schema_version": SCHEMA_VERSION,
        "cases": cases,
    }


def _render(data: dict[str, object]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def run() -> int:
    expected = _render(build())
    if not os.path.exists(FIXTURE):
        print(f"FAIL: {FIXTURE} missing; regenerate with "
              f"'python tests/test_diag_model_fixtures.py --write'")
        return 1
    with open(FIXTURE, encoding="utf-8") as f:
        actual = f.read()
    if actual != expected:
        print(f"FAIL: {FIXTURE} is stale (the model or the cases changed); "
              f"regenerate with 'python tests/test_diag_model_fixtures.py --write' "
              f"and re-run the Rust side (cd rust && cargo test -p own-diagnostics)")
        return 1
    data = json.loads(actual)
    cases = data["cases"]
    if data.get("schema_version") != SCHEMA_VERSION:
        print(f"FAIL: {FIXTURE} schema_version "
              f"{data.get('schema_version')!r} != {SCHEMA_VERSION}")
        return 1
    n_records = sum(len(c["records"]) for c in cases)
    n_distinct = sum(c["distinct_records"] for c in cases)
    print(f"diagnostic model fixtures OK: {len(cases)} cases "
          f"({n_records} records, {n_distinct} distinct) verified in sync")
    return 0


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
        with open(FIXTURE, "w", encoding="utf-8") as f:
            f.write(_render(build()))
        print(f"wrote {FIXTURE}")
        raise SystemExit(0)
    raise SystemExit(run())
