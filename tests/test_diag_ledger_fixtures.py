#!/usr/bin/env python3
"""Complete diagnostic-family ledger (P-022 step 5a, issue #255) — Python side.

PR 3 of three, and the one that closes #255. PR 1 pinned structural identity,
PR 2 pinned canonical rendering and emission order — both on curated shapes.
This slice makes the coverage **total and self-policing**: every code in
`ownlang.diagnostics.TITLES` gets a fixture case, and a new family cannot be
added without one.

## What the ledger proves, and what it deliberately does not

A case here constructs a real `Diagnostic` and freezes the reference's rendering
of it. That pins the **diagnostic-layer** contract for that code — message,
severity, subject, resource kind, ordered Evidence, and the exact text — which
is what #255 is about.

It does **not** claim the analyzer fires that code on any particular input.
That is step 4's contract (#214), already pinned by `tests/fixtures/diag_parity.json`
over the real `.own` corpus. The two are different questions and the ledger says
which is which per code: `analyzer_corpus: true` means the `.own` sweep actually
produces it today.

That distinction is the honest part. The `.own` sweep exercises **13 of 47**
codes; the rest are either bridge-only families (DI/EFF/OBL come from
`ownlang.ownir`, not the `.own` core) or core codes no corpus input happens to
reach. Silently rendering all 47 and calling it "full parity" would overstate
the evidence, so the coverage flag is carried per code and summarised.

## The three failure modes it closes

* **missing** — a code in `TITLES` with no case. The replay fails naming it, so
  adding a diagnostic without a fixture is a red build.
* **orphan** — a case whose code is not in `TITLES`. Catches a removed or
  renamed code leaving a fixture behind.
* **stale** — the generated file differs from what the current reference
  produces (the standing `--write` discipline, as in the other two slices).

Run:  python tests/test_diag_ledger_fixtures.py            (verify)
      python tests/test_diag_ledger_fixtures.py --write    (regenerate)
      python tests/run_tests.py                            (runs it as part of the suite)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.diagnostics import TITLES, Diagnostic, Evidence, Severity

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "diag_ledger.json")
CORPUS_PARITY = os.path.join(os.path.dirname(__file__), "fixtures", "diag_parity.json")

SCHEMA_VERSION = 1

# The anchor path every ledger case renders against; a fixed value keeps the
# golden diffable when a case is added in the middle.
_PATH = "src/Ledger.cs"


def _corpus_codes() -> set[str]:
    """Codes the real `.own` corpus sweep actually produces today.

    Read from the step-4 fixture rather than restated, so this flag cannot drift
    from the analyzer's true reach."""
    with open(CORPUS_PARITY, encoding="utf-8") as f:
        data = json.load(f)
    return {code for case in data["cases"] for _line, code in case["diags"]}


def _family(code: str) -> str:
    match = re.match(r"[A-Z]+", code)
    return match.group(0) if match else "?"


def _seed(code: str) -> int:
    """A stable per-code value, independent of the code's position in TITLES.

    Deliberately NOT the sorted index. Adding a family is the single event this
    ledger exists to make visible, and an index-derived shape sabotages exactly
    that: inserting one code shifts every later index, so `DI006` would rewrite
    42 of 47 existing records (measured). A one-record change is reviewable at a
    glance; 42 records of churn hide whether the renderer also moved.

    SHA-256 rather than `hash()`, whose string hashing is randomised per process
    and would make the golden unreproducible."""
    digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _shape_for(code: str) -> Diagnostic:
    """A representative `Diagnostic` for `code`.

    The message is derived from the reference's own TITLE (so it is meaningful
    and cannot drift from the vocabulary), with a quoted subject spliced in so
    the caret heuristic has something to find. Optional fields rotate by the
    code's own [`_seed`], so the ledger exercises every shape across the family
    set rather than 47 copies of one -- and each code's shape is fixed for good,
    whatever else joins the vocabulary.
    """
    title = TITLES[code]
    message = f"'{code.lower()}_subject' -- {title}"
    seed = _seed(code)
    line = seed % 900 + 1
    kwargs: dict[str, object] = {}
    if seed % 2 == 0:
        kwargs["subject"] = f"{code.lower()}_subject#{line}"
    if seed % 3 == 0:
        kwargs["resource_kind"] = "subscription token"
    if seed % 5 == 0:
        kwargs["severity"] = Severity.WARNING
    if seed % 4 == 0:
        kwargs["evidence"] = (
            Evidence(line=1, label="acquired here", role="acquired"),
            Evidence(line=2, label="escapes here", role="escaped",
                     file="src/Other.cs"),
        )
    elif seed % 4 == 1:
        kwargs["evidence"] = (Evidence(line=1, label="related step"),)
    return Diagnostic(code=code, message=message, line=line, **kwargs)  # type: ignore[arg-type]


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
    corpus = _corpus_codes()
    cases: list[dict[str, object]] = []
    for code in sorted(TITLES):
        diag = _shape_for(code)
        cases.append({
            "code": code,
            "family": _family(code),
            # True when the real `.own` corpus sweep produces this code today
            # (read from diag_parity.json, never restated).
            "analyzer_corpus": code in corpus,
            "title": TITLES[code],
            "path": _PATH,
            "diagnostic": _diagnostic_json(diag),
            "rendered": diag.render(_PATH),
        })

    families: dict[str, int] = {}
    for case in cases:
        family = str(case["family"])
        families[family] = families.get(family, 0) + 1

    return {
        "comment": (
            "GENERATED by tests/test_diag_ledger_fixtures.py --write; do not edit. "
            "Python (ownlang) is authoritative. The COMPLETE diagnostic-family ledger "
            "(P-022 step 5a, issue #255, PR 3 of 3): every TITLES code has a case, so a "
            "new family cannot ship without a fixture. `analyzer_corpus` records whether "
            "the real .own sweep produces that code today -- rendering coverage is not "
            "the same claim as analyzer coverage, and this file does not conflate them."
        ),
        "schema_version": SCHEMA_VERSION,
        "totals": {
            "codes": len(cases),
            "by_family": dict(sorted(families.items())),
            "analyzer_corpus": sum(1 for c in cases if c["analyzer_corpus"]),
        },
        "cases": cases,
    }


def _render_json(data: dict[str, object]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def run() -> int:
    expected = _render_json(build())
    if not os.path.exists(FIXTURE):
        print(f"FAIL: {FIXTURE} missing; regenerate with "
              f"'python tests/test_diag_ledger_fixtures.py --write'")
        return 1
    with open(FIXTURE, encoding="utf-8") as f:
        actual = f.read()
    if actual != expected:
        print(f"FAIL: {FIXTURE} is stale (a code, title or renderer changed); "
              f"regenerate with 'python tests/test_diag_ledger_fixtures.py --write' "
              f"and re-run the Rust side (cd rust && cargo test -p own-diagnostics)")
        return 1

    data = json.loads(actual)
    if data.get("schema_version") != SCHEMA_VERSION:
        print(f"FAIL: {FIXTURE} schema_version "
              f"{data.get('schema_version')!r} != {SCHEMA_VERSION}")
        return 1

    # The two failure modes the LEDGER exists for, asserted on the Python side
    # too so a regeneration cannot quietly paper over either.
    covered = {str(case["code"]) for case in data["cases"]}
    missing = sorted(set(TITLES) - covered)
    orphans = sorted(covered - set(TITLES))
    if missing:
        print(f"FAIL: {len(missing)} code(s) in TITLES have no ledger case: {missing}")
        return 1
    if orphans:
        print(f"FAIL: {len(orphans)} ledger case(s) name a code absent from TITLES: "
              f"{orphans}")
        return 1

    churn = _insertion_churn()
    if churn:
        print(f"FAIL: inserting one code rewrote {churn} existing ledger record(s). "
              f"Shapes must derive from the code itself, never from its position in "
              f"the sorted vocabulary — adding a family has to be a ONE-record diff, "
              f"or a real renderer change hides in the churn")
        return 1

    totals = data["totals"]
    print(f"diagnostic ledger OK: {totals['codes']}/{len(TITLES)} codes covered "
          f"({totals['by_family']}), "
          f"{totals['analyzer_corpus']} of them also produced by the .own corpus sweep; "
          f"a new code rewrites {churn} existing record(s)")
    return 0


def _insertion_churn() -> int:
    """How many EXISTING records change when one new code joins the vocabulary.

    Must be zero. This is the property that makes the ledger readable: the whole
    point is that adding a diagnostic family shows up as a single new record a
    reviewer can check, not as a wall of unrelated edits. An index-derived shape
    scored 42 of 47 here before the seed was made position-independent.

    A probe code is inserted mid-vocabulary (so it shifts sorted positions) and
    removed again in a `finally`, so the live TITLES the rest of the suite sees
    is untouched."""
    probe = "DI999"
    if probe in TITLES:  # pragma: no cover - defensive
        return 0
    before = {case["code"]: case for case in build()["cases"]}
    TITLES[probe] = "ledger insertion probe (not a real diagnostic)"
    try:
        after = {case["code"]: case for case in build()["cases"]}
    finally:
        del TITLES[probe]
    shared = set(before) & set(after) - {probe}
    return sum(1 for code in shared if before[code] != after[code])


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
        with open(FIXTURE, "w", encoding="utf-8") as f:
            f.write(_render_json(build()))
        print(f"wrote {FIXTURE}")
        raise SystemExit(0)
    raise SystemExit(run())
