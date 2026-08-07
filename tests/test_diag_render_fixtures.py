#!/usr/bin/env python3
"""Canonical rendering + ordering parity fixtures (P-022 step 5a, issue #255) — Python side.

PR 2 of three. PR 1 froze the *structural identity* of a diagnostic
(`tests/fixtures/diag_model.json`); it deliberately treated `message` as an
opaque string and asserted ordering only as a *property* (total, antisymmetric,
reproducible). This fixture supplies the two things it left open:

1. the **canonical rendered text** — `Diagnostic.render`, `render_pretty`,
   `title`, the ` [resource: ...]` suffix and the `note:` evidence lines;
2. the **emission ordering contract** — what sequence the core actually emits.

A separate file on purpose: PR 1's schema was declared final, and later slices
were promised they would *add cases, never reshape a record*. Bolting expected
strings onto `diag_model.json` would have broken that promise on the first
follow-up, so the rendering contract gets its own schema and its own generator.

## The ordering contract is narrower than PR 1's key — and that matters

`ownlang.__main__.check_module` ends with:

    diags.sort(key=lambda d: (d.line, d.code))

Python's `list.sort` is **stable**, so this is *not* a total order over the
record: two diagnostics with equal `(line, code)` keep their **emission** order
(policies -> lifetimes -> per function: CFG diagnostics, then analysis
diagnostics). A port that sorts by the full identity, or that uses an unstable
sort, reproduces the same *set* in the wrong *sequence*.

Note also what the key does **not** contain: the path. Within one module every
diagnostic shares a file, so the core never orders by it. Cross-file ordering is
a different layer's contract (`ownlang.di`/`ownlang.effects` sort their own
finding types by `(file, line, ...)`), and inventing it here would be a
behaviour the reference does not have.

## Why the caret column is a parity hazard

`render_pretty` places a caret with `_caret_col`, which is a *renderer
heuristic* — not the #317 source column PR 1 modelled. It searches the first
single-quoted identifier in the message, prefers a word-boundary match, falls
back to a plain substring, and finally to the line's indent.

Python's `str.find` and `re.match.start()` return **character** offsets. Rust's
`str::find` returns a **byte** offset. On any non-ASCII source line the two
disagree, silently, and the caret lands mid-glyph. The `unicode_*` cases below
exist to make that divergence fail loudly rather than look plausible.

Run:  python tests/test_diag_render_fixtures.py            (verify)
      python tests/test_diag_render_fixtures.py --write    (regenerate)
      python tests/run_tests.py                            (runs it as part of the suite)
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.diagnostics import Diagnostic, Evidence, Severity

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "diag_render.json")

# Independent of diag_model.json's version: this is a different contract with a
# different shape, and the two must be free to move apart.
SCHEMA_VERSION = 1

# Non-ASCII rendering inputs, one literal per line so a confusable-character lint
# stays reviewable at the string it fires on.
_RU_LINE = "    освободить поток;"
_RU_NAME = "поток"
_RU_MESSAGE = "'поток' освобождён дважды"
_JA_LINE = "    リソース を 解放 する;"
_JA_NAME = "リソース"


def _d(code: str, message: str, line: int, **kw: object) -> Diagnostic:
    return Diagnostic(code=code, message=message, line=line, **kw)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Rendering cases: one record + the exact text the reference produces for it.
# `source` is optional; when present, render_pretty is pinned too.
# ---------------------------------------------------------------------------
_RENDER: list[tuple[str, str, str, Diagnostic, str | None]] = [
    (
        "plain_minimal",
        "the base line: file:line: severity: [code] message, nothing else",
        "src/A.cs",
        _d("OWN003", "double release", 7),
        None,
    ),
    (
        "resource_kind_suffix",
        "the domain-neutral ` [resource: ...]` tail a profile keys off",
        "src/A.cs",
        _d("OWN001", "not released", 12, resource_kind="subscription token"),
        None,
    ),
    (
        "resource_kind_unknown_value",
        "an unrecognised kind is rendered verbatim -- the suffix is a passthrough, "
        "not a lookup, so a new profile's tag needs no renderer change",
        "src/A.cs",
        _d("OWN001", "not released", 12, resource_kind="quantum flux capacitor"),
        None,
    ),
    (
        "warning_severity",
        "the P-004 warning tier renders its own severity word",
        "src/A.cs",
        _d("OWN001", "may not be released", 12, severity=Severity.WARNING),
        None,
    ),
    (
        "evidence_same_file_uses_the_anchor",
        "`file=None` means 'the anchor's own file', and the note resolves it",
        "src/A.cs",
        _d("OWN001", "not released", 12, evidence=(
            Evidence(line=4, label="acquired here", role="acquired"),
        )),
        None,
    ),
    (
        "evidence_cross_file_keeps_its_own",
        "an explicit step file wins over the anchor -- the DI captive shape",
        "src/Vm.cs",
        _d("DI001", "captive dependency", 9, evidence=(
            Evidence(line=3, label="registered here", file="src/Startup.cs"),
        )),
        None,
    ),
    (
        "evidence_order_is_rendered_in_order",
        "note lines follow the slice order; the slice IS the reachability path",
        "src/Flow.cs",
        _d("OWN014", "value escapes", 30, evidence=(
            Evidence(line=10, label="acquired here", role="acquired"),
            Evidence(line=20, label="escapes here", role="escaped"),
            Evidence(line=25, label="promoted here", role="step"),
        )),
        None,
    ),
    (
        "di004_root_provider_anchor",
        "a real DI004 with its subject and consuming-context note",
        "src/Svc.cs",
        _d("DI004", "scoped 'Repo' resolved from the root provider", 41,
           subject="Repo#41", evidence=(
               Evidence(line=12, label="singleton 'Cache' (captor)", role="related"),
           )),
        None,
    ),
    (
        "di005_cache_site_anchor",
        "DI005 anchors at the field store, not the scope creation",
        "src/Svc.cs",
        _d("DI005", "scope-resolved 'Repo' cached into a field", 55,
           subject="_repo#55", evidence=(
               Evidence(line=50, label="scope created here", role="acquired"),
               Evidence(line=55, label="cached here", role="escaped"),
           )),
        None,
    ),
    # ---- render_pretty / caret placement ----
    (
        "caret_on_quoted_identifier",
        "the caret lands on the first single-quoted name in the message",
        "src/A.cs",
        _d("OWN002", "use 'b' after it was released", 3),
        "fn f() {\n    let a = 1;\n    Hash(b);\n}\n",
    ),
    (
        "caret_prefers_a_word_boundary",
        "'a' must land on the ARGUMENT in `Hash(a)`, not on the 'a' inside 'Hash' "
        "-- the word-boundary attempt is tried before a plain substring search",
        "src/A.cs",
        _d("OWN002", "use 'a' after it was released", 3),
        "fn f() {\n    let a = 1;\n    Hash(a);\n}\n",
    ),
    (
        "caret_falls_back_to_substring",
        "no word-boundary match exists, so the plain substring position is used",
        "src/A.cs",
        _d("OWN002", "use 'ash' after it was released", 3),
        "fn f() {\n    let a = 1;\n    Hash(a);\n}\n",
    ),
    (
        "caret_falls_back_to_indent_without_a_quote",
        "an unquoted message has no name to point at, so the caret goes to the "
        "first non-blank column",
        "src/A.cs",
        _d("OWN020", "unsupported construct", 3),
        "fn f() {\n    let a = 1;\n        deeply(indented);\n}\n",
    ),
    (
        "caret_is_absent_on_a_blank_line",
        "a blank source line yields no column at all -- the header degrades to "
        "file:line and the source/caret block is omitted entirely",
        "src/A.cs",
        _d("OWN020", "unsupported construct", 2),
        "fn f() {\n\n}\n",
    ),
    (
        "caret_when_the_line_is_out_of_range",
        "a line past the end of the source falls back to the plain header",
        "src/A.cs",
        _d("OWN020", "unsupported construct", 99),
        "fn f() {\n}\n",
    ),
    (
        "unicode_caret_counts_characters_not_bytes",
        "THE byte-vs-char trap: Python reports a CHARACTER offset, Rust's str::find "
        "reports a BYTE offset. On this Cyrillic line the two differ, so a port that "
        "forwards a byte index puts the caret mid-glyph",
        "src/Отчёт.cs",
        _d("OWN003", _RU_MESSAGE, 1),
        _RU_LINE + "\n",
    ),
    (
        "unicode_caret_wide_glyphs",
        "the same trap with 3-byte characters, where a byte offset overshoots by more",
        "src/報告.cs",
        _d("OWN001", f"'{_JA_NAME}' が解放されていません", 1),
        _JA_LINE + "\n",
    ),
    (
        "message_with_several_quoted_names",
        "only the FIRST quoted group is the subject -- a later name must not steal "
        "the caret",
        "src/A.cs",
        _d("OWN007", "move 'a' while 'b' is borrowed", 3),
        "fn f() {\n    let b = 1;\n    let a = move b;\n}\n",
    ),
    (
        "message_with_an_unmatched_quote",
        "a single unpaired quote matches no group, so the indent fallback applies",
        "src/A.cs",
        _d("OWN020", "it's complicated", 3),
        "fn f() {\n    let a = 1;\n    whatever();\n}\n",
    ),
]


# ---------------------------------------------------------------------------
# Ordering cases: an EMISSION sequence and the sequence `check_module` produces
# from it. Records are labelled so a reordering is visible in the golden.
# ---------------------------------------------------------------------------
_ORDER: list[tuple[str, str, list[tuple[str, Diagnostic]]]] = [
    (
        "sorts_by_line_then_code",
        "the plain case: the key is (line, code), in that precedence",
        [
            ("c", _d("OWN003", "third", 9)),
            ("a", _d("OWN001", "first", 2)),
            ("b", _d("OWN002", "second", 9)),
        ],
    ),
    (
        "ties_keep_emission_order",
        "THE stability control: equal (line, code) must preserve INPUT order. An "
        "unstable sort, or a sort over the full record, reproduces the same set in "
        "the wrong sequence",
        [
            ("emitted-1", _d("OWN001", "zulu", 5, subject="z#5")),
            ("emitted-2", _d("OWN001", "alpha", 5, subject="a#5")),
            ("emitted-3", _d("OWN001", "mike", 5, subject="m#5")),
        ],
    ),
    (
        "ties_ignore_severity_and_evidence",
        "severity and the evidence slice are NOT in the key -- they must not "
        "perturb a tie either",
        [
            ("warn-first", _d("OWN001", "x", 5, severity=Severity.WARNING)),
            ("error-second", _d("OWN001", "x", 5, severity=Severity.ERROR,
                                evidence=(Evidence(line=1, label="a"),))),
        ],
    ),
    (
        "path_is_not_part_of_the_core_key",
        "within one module every diagnostic shares a file, so the core key has no "
        "path component; equal-line records from different notional files order by "
        "code alone and otherwise keep emission order. Cross-file ordering belongs "
        "to the finding layers (ownlang.di / ownlang.effects), not here",
        [
            ("from-z-file", _d("OWN002", "z", 7)),
            ("from-a-file", _d("OWN002", "a", 7)),
            ("from-m-file", _d("OWN001", "m", 7)),
        ],
    ),
    (
        "code_order_is_lexicographic_not_numeric",
        "codes are compared as STRINGS: 'OWN010' sorts before 'OWN009' would if "
        "numbers were parsed, and before 'OWN2' regardless -- pinning this stops a "
        "port from 'helpfully' comparing the numeric tail",
        [
            ("own9", _d("OWN009", "nine", 4)),
            ("own10", _d("OWN010", "ten", 4)),
            ("di1", _d("DI001", "di", 4)),
            ("eff1", _d("EFF001", "eff", 4)),
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


def build() -> dict[str, object]:
    render_cases: list[dict[str, object]] = []
    for name, why, path, diag, source in _RENDER:
        case: dict[str, object] = {
            "name": name,
            "why": why,
            "path": path,
            "diagnostic": _diagnostic_json(diag),
            "title": diag.title,
            "source": source,
            "rendered": diag.render(path),
        }
        # render_pretty is pinned only where a source text exists to render against.
        case["rendered_pretty"] = (
            diag.render_pretty(path, source) if source is not None else None
        )
        render_cases.append(case)

    order_cases: list[dict[str, object]] = []
    for name, why, labelled in _ORDER:
        # Reproduce `check_module`'s final step EXACTLY -- same key, same stable
        # sort -- rather than restating the intended order by hand.
        ordered = sorted(labelled, key=lambda pair: (pair[1].line, pair[1].code))
        order_cases.append({
            "name": name,
            "why": why,
            "emitted": [
                {"label": label, "diagnostic": _diagnostic_json(d)}
                for label, d in labelled
            ],
            "ordered_labels": [label for label, _ in ordered],
        })

    return {
        "comment": (
            "GENERATED by tests/test_diag_render_fixtures.py --write; do not edit. "
            "Python (ownlang) is authoritative. Canonical rendering (Diagnostic.render / "
            "render_pretty / title / resource-kind suffix / note lines) and the emission "
            "ordering contract from ownlang.__main__.check_module -- a STABLE sort on "
            "(line, code), so ties keep emission order (P-022 step 5a, issue #255, PR 2 of 3). "
            "rust/crates/own-diagnostics replays every case with zero Python."
        ),
        "schema_version": SCHEMA_VERSION,
        "render_cases": render_cases,
        "order_cases": order_cases,
    }


def _render_json(data: dict[str, object]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def run() -> int:
    expected = _render_json(build())
    if not os.path.exists(FIXTURE):
        print(f"FAIL: {FIXTURE} missing; regenerate with "
              f"'python tests/test_diag_render_fixtures.py --write'")
        return 1
    with open(FIXTURE, encoding="utf-8") as f:
        actual = f.read()
    if actual != expected:
        print(f"FAIL: {FIXTURE} is stale (the renderer or the cases changed); "
              f"regenerate with 'python tests/test_diag_render_fixtures.py --write' "
              f"and re-run the Rust side (cd rust && cargo test -p own-diagnostics)")
        return 1
    data = json.loads(actual)
    if data.get("schema_version") != SCHEMA_VERSION:
        print(f"FAIL: {FIXTURE} schema_version "
              f"{data.get('schema_version')!r} != {SCHEMA_VERSION}")
        return 1
    n_pretty = sum(1 for c in data["render_cases"] if c["rendered_pretty"] is not None)
    print(f"diagnostic render fixtures OK: {len(data['render_cases'])} render cases "
          f"({n_pretty} with a caret rendering), "
          f"{len(data['order_cases'])} ordering cases verified in sync")
    return 0


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
        with open(FIXTURE, "w", encoding="utf-8") as f:
            f.write(_render_json(build()))
        print(f"wrote {FIXTURE}")
        raise SystemExit(0)
    raise SystemExit(run())
