#!/usr/bin/env python3
"""Controls for P-037's A2.0 evidence freshness predicate.

These are structure controls, not a second implementation of the predicate:
the live repository supplies one real evidence record, then each control
corrupts exactly one claim and requires the shared gate to refuse it.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import p037_evidence as ev  # noqa: E402

failures = 0


def ok(name: str) -> None:
    print(f"ok[{name}]")


def fail(name: str, detail: str) -> None:
    global failures
    failures += 1
    print(f"FAIL[{name}]: {detail}")


def require_problem(name: str, record: dict[str, object], needle: str) -> None:
    problems = ev.provenance_problems(record)
    if any(needle in problem for problem in problems):
        ok(name)
    else:
        fail(name, f"expected a problem containing {needle!r}, got {problems!r}")


def require_pair_problem(
    name: str,
    before: dict[str, object],
    after: dict[str, object],
    needle: str,
) -> None:
    problems = ev.comparison_problems(before, after)
    if any(needle in problem for problem in problems):
        ok(name)
    else:
        fail(name, f"expected a pair problem containing {needle!r}, got {problems!r}")


def main() -> int:
    problems = ev.closure_problems()
    if problems:
        fail("runtime-closure-covered", "; ".join(problems))
        return 1
    ok("runtime-closure-covered")

    record = ev.evidence_fields(("corpus/p037-shapes",))
    live = ev.provenance_problems(record)
    if live:
        fail("fresh-record-valid", "; ".join(live))
        return 1
    ok("fresh-record-valid")

    manifest_paths = [
        entry["path"] for entry in record["input_manifest"]
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    ]
    live_paths = [
        path.relative_to(ROOT).as_posix()
        for path in ev.input_paths(("corpus/p037-shapes",))
    ]
    if live_paths != manifest_paths:
        fail("execution-denominator-is-manifest", f"{live_paths!r} != {manifest_paths!r}")
    else:
        ok("execution-denominator-is-manifest")

    pair_before = copy.deepcopy(record)
    pair_after = copy.deepcopy(record)
    pair_before["toolchains"] = {"python": "test", "dotnet": "test", "platform": "test"}
    pair_after["toolchains"] = {"python": "test", "dotnet": "test", "platform": "test"}
    pair_live = ev.comparison_problems(pair_before, pair_after)
    if pair_live:
        fail("comparison-accepts-two-honest-records", "; ".join(pair_live))
    else:
        ok("comparison-accepts-two-honest-records")
    pair_after["is_evidence"] = False
    require_pair_problem(
        "comparison-refuses-non-evidence",
        pair_before,
        pair_after,
        "is_evidence=true",
    )

    missing_subject = copy.deepcopy(record)
    missing_subject["subject_paths"] = list(ev.SUBJECT_PATHS[:-1])
    require_problem(
        "closure-expansion-invalidates",
        missing_subject,
        "subject_paths differ",
    )

    tampered_manifest = copy.deepcopy(record)
    manifest = tampered_manifest["input_manifest"]
    assert isinstance(manifest, list) and manifest
    first = manifest[0]
    assert isinstance(first, dict)
    first["blob"] = "0" * 40
    require_problem(
        "input-manifest-tamper-refused",
        tampered_manifest,
        "input_manifest",
    )

    non_evidence = copy.deepcopy(record)
    non_evidence["is_evidence"] = False
    require_problem(
        "non-evidence-refused",
        non_evidence,
        "is_evidence=true",
    )

    if failures:
        print(f"RESULT: {failures} provenance control(s) failed")
        return 1
    print("RESULT: all P-037 evidence provenance controls passed")
    return 0


def run() -> int:
    """Entry point required by tests/run_tests.py's test_*.py census."""
    return main()


if __name__ == "__main__":
    raise SystemExit(run())
