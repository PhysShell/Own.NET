#!/usr/bin/env python3
"""SARIF 2.1.0 projection parity (P-022 step 5b, issue #256) — Python side.

Freezes `ownlang.diag_sarif.build_sarif` — the `.own` flow-diagnostic SARIF path
behind `check --format sarif` — so the Rust port can replay it with zero Python.

## Which SARIF surface this is, and which it is not

The repo has **two** SARIF builders:

* `ownlang.diag_sarif.build_sarif` over `diagnostics.Diagnostic` — this one. It
  depends only on `diagnostics` and `evidence`, both pure, which is exactly the
  reach `own-diagnostics` is allowed under the P-022 crate DAG.
* `ownlang.ownir.build_sarif` over `ownir.Finding` — the C#/DI path. It needs
  OwnIR, and #256's own guardrail says "no OwnIR bridge", so it is **out of
  scope here**. That is why no DI004/DI005 case appears below: those codes are
  produced by the OwnIR path, and porting them would cross the DAG boundary
  this step is meant to respect. They land with the bridge (#259), not here.

## The canonical comparison, and why it removes nothing

#256 asks for an enumerated list of volatile fields stripped before comparison,
and forbids a wildcard "ignore metadata" rule. The enumerated list is **empty**,
which is a measurement rather than a shortcut:

* the builder takes `(diags, filename, severity)` and reads no clock, no
  environment, no filesystem;
* it emits no timestamp, no GUID, no absolute path, no run id;
* building the same input twice is byte-identical (asserted in [`run`]).

So canonicalization is only about the one axis where two *correct* serializers
legitimately differ — **object key order**, which JSON declares unordered.
Arrays stay in place: `results`, `relatedLocations` and the `threadFlows`
locations are ordered contracts, and sorting them would erase the very thing
step 5b exists to pin.

## Ordering contracts pinned here

* `results` follow **input order**, not code order — `build_sarif` maps over
  `diags` as given. Two diagnostics sharing `(code, message)` at different lines
  must keep their emission order.
* `tool.driver.rules` are sorted by code, deduplicated.
* `relatedLocations` and `codeFlows[0].threadFlows[0].locations` follow evidence
  order.

Run:  python tests/test_sarif_parity_fixtures.py            (verify)
      python tests/test_sarif_parity_fixtures.py --write    (regenerate)
      python tests/run_tests.py                             (as part of the suite)
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.diag_sarif import build_sarif
from ownlang.diagnostics import Diagnostic, Evidence, Severity

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sarif_parity.json")

SCHEMA_VERSION = 1

# Every case carries these keys and no others; a reshape is a reviewed contract
# change, not something a regeneration slips through.
ROOT_KEYS = {"comment", "schema_version", "volatile_fields", "cases"}
CASE_KEYS = {"name", "why", "filename", "severity", "diagnostics", "sarif"}


def _ev(line: int, label: str, file: str | None = None,
        role: str = "related") -> Evidence:
    return Evidence(line=line, label=label, file=file, role=role)


def _cases() -> list[dict[str, Any]]:
    """One entry per control #256 requires of the diag_sarif path.

    Each is a hand-built `Diagnostic` list rather than analyzer output: the
    controls include shapes (empty `file`, empty `resource_kind`, file-level
    line 0) the analyzer does not currently produce but the *builder* must still
    handle, and pinning the builder is what step 5b is about.
    """
    return [
        {
            "name": "empty-result-set",
            "why": "no diagnostics: the log still declares schema/driver, with "
                   "an empty rules catalogue and empty results — a consumer must "
                   "get a well-formed log, not a missing one",
            "filename": "clean.own",
            "severity": "error",
            "diags": [],
        },
        {
            "name": "no-evidence",
            "why": "a diagnostic with no Evidence must carry NEITHER "
                   "relatedLocations NOR codeFlows — the keys are absent, not "
                   "present-and-empty",
            "filename": "d.own",
            "severity": "error",
            "diags": [Diagnostic(code="OWN003", message="double release of 'c'",
                                 line=3)],
        },
        {
            "name": "multi-step-code-flow",
            "why": "ordered reachability slice: codeFlows mirrors the evidence "
                   "order exactly, and relatedLocations carries the same steps",
            "filename": "esc.own",
            "severity": "error",
            "diags": [Diagnostic(
                code="OWN015", message="'b' escapes its region", line=4,
                subject="b#3:9",
                evidence=(_ev(3, "'b' allocated here", role="acquired"),
                          _ev(4, "escapes the function by return here",
                              role="escaped")))],
        },
        {
            "name": "multi-file-related-locations",
            "why": "Evidence.file overrides the diagnostic's own file; steps in "
                   "different artifacts must each point at their own uri",
            "filename": "main.own",
            "severity": "error",
            "diags": [Diagnostic(
                code="OWN016", message="'buf' outlives its frame", line=7,
                evidence=(_ev(2, "allocated here", file="alloc.own",
                              role="acquired"),
                          _ev(9, "stored here", file="store.own"),
                          _ev(7, "read after frame exit")))],
        },
        {
            "name": "evidence-file-empty-string",
            "why": "Python `e.file or filename` is TRUTHINESS, not None-ness: an "
                   "empty-string file falls back to the diagnostic's filename. A "
                   "port using Option-presence would emit an empty uri and make "
                   "the whole log unprocessable for code scanning",
            "filename": "anchor.own",
            "severity": "error",
            "diags": [Diagnostic(
                code="OWN001", message="'c' never released", line=5,
                evidence=(_ev(4, "'c' acquired here", file="", role="acquired"),))],
        },
        {
            "name": "evidence-dropped-file-level-line",
            "why": "a step with line < 1 is dropped from BOTH projections; here "
                   "the only step is dropped, so codeFlows collapses to [] and "
                   "the key is omitted entirely rather than emitted empty",
            "filename": "drop.own",
            "severity": "error",
            "diags": [Diagnostic(
                code="OWN002", message="use after release", line=6,
                evidence=(_ev(0, "file-level note"),))],
        },
        {
            "name": "diagnostic-file-level-line",
            "why": "the PRIMARY location omits `region` when line < 1 — a "
                   "file-level finding stays schema-valid instead of carrying a "
                   "bogus startLine",
            "filename": "modlevel.own",
            "severity": "error",
            "diags": [Diagnostic(code="OWN030", message="unknown buffer mode",
                                 line=0)],
        },
        {
            "name": "resource-kind-suffix",
            "why": "a non-empty resource_kind appends ' [resource: X]' to the "
                   "message text",
            "filename": "res.own",
            "severity": "error",
            "diags": [Diagnostic(code="OWN001", message="'h' never released",
                                 line=8, resource_kind="file handle")],
        },
        {
            "name": "resource-kind-empty-string",
            "why": "`if d.resource_kind` is TRUTHINESS: an empty-string kind adds "
                   "NO suffix. An Option-presence port would emit "
                   "' [resource: ]' — a real divergence in user-visible text",
            "filename": "res.own",
            "severity": "error",
            "diags": [Diagnostic(code="OWN001", message="'h' never released",
                                 line=8, resource_kind="")],
        },
        {
            "name": "tie-ordering-same-code-and-message",
            "why": "results follow INPUT order, not code order. Equal code AND "
                   "equal message at distinct lines must not be reordered or "
                   "collapsed; the rules catalogue still lists the code once",
            "filename": "ties.own",
            "severity": "error",
            "diags": [Diagnostic(code="OWN001", message="'c' never released",
                                 line=30),
                      Diagnostic(code="OWN001", message="'c' never released",
                                 line=10),
                      Diagnostic(code="OWN001", message="'c' never released",
                                 line=20)],
        },
        {
            "name": "rule-table-sorted-and-deduplicated",
            "why": "tool.driver.rules is sorted by code and deduplicated even "
                   "though results are not sorted — two independent orderings in "
                   "one log, and a port that sorts results to match the catalogue "
                   "would break emission order",
            "filename": "rules.own",
            "severity": "error",
            "diags": [Diagnostic(code="OWN016", message="second", line=2),
                      Diagnostic(code="OWN001", message="first", line=1),
                      Diagnostic(code="OWN016", message="third", line=3),
                      Diagnostic(code="OWN008", message="fourth", line=4)],
        },
        {
            "name": "severity-error-default",
            "why": "an ERROR diagnostic under the default severity maps to level "
                   "'error'",
            "filename": "sev.own",
            "severity": "error",
            "diags": [Diagnostic(code="OWN001", message="m", line=1,
                                 severity=Severity.ERROR)],
        },
        {
            "name": "severity-warning-override",
            "why": "severity='warning' is a PRESENTATION choice: it sets every "
                   "result's level to warning regardless of the diagnostic",
            "filename": "sev.own",
            "severity": "warning",
            "diags": [Diagnostic(code="OWN001", message="m", line=1,
                                 severity=Severity.ERROR)],
        },
        {
            "name": "severity-intrinsic-warning-survives-error-request",
            "why": "an intrinsically WARNING diagnostic stays 'warning' even when "
                   "the caller asks for 'error' — the override raises, never "
                   "lowers. Note the core has only ERROR and WARNING: no SARIF "
                   "'note' level is produced by this path today",
            "filename": "sev.own",
            "severity": "error",
            "diags": [Diagnostic(code="OWN012", message="advisory", line=2,
                                 severity=Severity.WARNING),
                      Diagnostic(code="OWN001", message="hard", line=3,
                                 severity=Severity.ERROR)],
        },
        {
            "name": "windows-drive-path",
            "why": "backslashes are normalized to forward slashes in every uri, "
                   "including evidence steps — a Windows-produced log must be "
                   "consumable by GitHub code scanning",
            "filename": r"C:\src\App\Main.own",
            "severity": "error",
            "diags": [Diagnostic(
                code="OWN001", message="'c' never released", line=12,
                evidence=(_ev(4, "acquired here", role="acquired"),
                          _ev(9, "escapes here", file=r"C:\src\App\Other.own",
                              role="escaped")))],
        },
        {
            "name": "non-ascii-path",
            "why": "non-ASCII path segments survive unescaped through the uri; "
                   "the fixture is written with ensure_ascii=False so a mangled "
                   "encoding shows up as a diff instead of hiding behind \\u",
            "filename": "src/модуль/файл.own",
            "severity": "error",
            "diags": [Diagnostic(
                code="OWN001", message="'дескриптор' never released", line=5,
                resource_kind="файловый дескриптор",
                evidence=(_ev(3, "получен здесь", role="acquired"),))],
        },
    ]


def _evidence_json(ev: Evidence) -> dict[str, Any]:
    return {"line": ev.line, "label": ev.label, "file": ev.file, "role": ev.role}


def _diagnostic_json(d: Diagnostic) -> dict[str, Any]:
    return {
        "code": d.code,
        "message": d.message,
        "line": d.line,
        "severity": d.severity.value,
        "subject": d.subject,
        "resource_kind": d.resource_kind,
        "evidence": [_evidence_json(e) for e in d.evidence],
    }


def build() -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for spec in _cases():
        diags: list[Diagnostic] = spec["diags"]
        cases.append({
            "name": spec["name"],
            "why": spec["why"],
            "filename": spec["filename"],
            "severity": spec["severity"],
            "diagnostics": [_diagnostic_json(d) for d in diags],
            "sarif": build_sarif(diags, spec["filename"], spec["severity"]),
        })
    return {
        "comment": (
            "GENERATED by tests/test_sarif_parity_fixtures.py --write; do not edit. "
            "Python (ownlang.diag_sarif) is authoritative. SARIF 2.1.0 projection "
            "parity for P-022 step 5b, issue #256 -- the .own flow-diagnostic path "
            "only. The OwnIR/C# path (ownlang.ownir.build_sarif, DI/EFF/OBL codes) "
            "is deliberately NOT covered: it would cross the crate-DAG boundary "
            "#256 exists to respect."
        ),
        "schema_version": SCHEMA_VERSION,
        "volatile_fields": [],
        "cases": cases,
    }


def _render_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def canonical(node: Any) -> Any:
    """The canonical form both sides compare.

    Object keys are sorted because JSON declares objects unordered and two
    correct serializers may disagree there. Arrays are left ALONE: `results`,
    `relatedLocations` and thread-flow locations are ordered contracts, and
    sorting them would erase exactly what this fixture pins.
    """
    if isinstance(node, dict):
        return {k: canonical(node[k]) for k in sorted(node)}
    if isinstance(node, list):
        return [canonical(v) for v in node]
    return node


def _volatile_census(data: dict[str, Any]) -> list[str]:
    """Tokens that would force a field onto the volatile list, if any existed.

    #256 forbids a wildcard 'ignore metadata' rule and demands each removed
    field be justified. The list is empty, so this looks for the things that
    would populate it -- an ISO timestamp, a GUID, an absolute path -- and
    reports any hit rather than asserting emptiness by assumption.
    """
    blob = json.dumps(data, ensure_ascii=False)
    patterns = {
        "iso-timestamp": r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}",
        "guid": r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-",
        "posix-abs-path": r'"/(?:home|tmp|Users|var)/',
        "nt-abs-path": r'"[A-Za-z]:\\\\(?!src)',
    }
    return [name for name, pat in patterns.items() if re.search(pat, blob)]


def run() -> int:
    fresh = build()
    expected = _render_json(fresh)
    if not os.path.exists(FIXTURE):
        print(f"FAIL: {FIXTURE} missing; regenerate with "
              f"'python tests/test_sarif_parity_fixtures.py --write'")
        return 1
    with open(FIXTURE, encoding="utf-8") as f:
        actual = f.read()
    if actual != expected:
        print(f"FAIL: {FIXTURE} is stale (the SARIF projection changed); "
              f"regenerate with 'python tests/test_sarif_parity_fixtures.py --write' "
              f"and re-run the Rust side (cd rust && cargo test -p own-diagnostics)")
        return 1

    data = json.loads(actual)
    if set(data) != ROOT_KEYS:
        print(f"FAIL: fixture root keys {sorted(data)} != {sorted(ROOT_KEYS)}")
        return 1
    if data.get("schema_version") != SCHEMA_VERSION:
        print(f"FAIL: schema_version {data.get('schema_version')!r} "
              f"!= {SCHEMA_VERSION}")
        return 1
    for case in data["cases"]:
        if set(case) != CASE_KEYS:
            print(f"FAIL: case {case.get('name')!r} keys {sorted(case)} "
                  f"!= {sorted(CASE_KEYS)}")
            return 1

    # The builder must be a pure function of its arguments: same input twice,
    # byte-identical output. This is what makes the volatile-field list empty.
    if _render_json(build()) != expected:
        print("FAIL: build_sarif is not deterministic — two builds of the same "
              "input differ, so the canonical comparison would need volatile "
              "fields enumerated")
        return 1

    hits = _volatile_census(data)
    if hits:
        print(f"FAIL: the log now carries volatile content ({hits}). "
              f"'volatile_fields' is declared empty; either the field is "
              f"non-semantic and must be enumerated with a reason, or it does "
              f"not belong in the log")
        return 1
    if data["volatile_fields"] != []:
        print(f"FAIL: volatile_fields is {data['volatile_fields']!r}; the census "
              f"found nothing to strip, so it must stay empty")
        return 1

    results = sum(len(c["sarif"]["runs"][0]["results"]) for c in data["cases"])
    print(f"sarif parity OK: {len(data['cases'])} cases, {results} results, "
          f"0 volatile fields stripped (census clean), builder deterministic")
    return 0


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
        with open(FIXTURE, "w", encoding="utf-8") as f:
            f.write(_render_json(build()))
        print(f"wrote {FIXTURE}")
        raise SystemExit(0)
    raise SystemExit(run())
