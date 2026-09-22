#!/usr/bin/env python3
"""P-037 A2.2-S: the cumulative-evidence driver's classifier and readers hold their controls.

Runs no tool. The driver (scripts/p037_cumulative_evidence.py) orchestrates the
four governed takes, the fact-diff classification and the anchored layer
differential of the one measurement that closes the A2 treatment. This test
pins the parts that decide without dotnet: a guarded-only fact diff is the
allowed surface and nothing else is (a legacy body, a signature, services,
components, stats, the schema version, a new top-level key, an added function
are UNEXPECTED by path); the baseline manifest's digests parse; the snapshot
tools' RESULT lines parse; a capture's three layers digest and move only with
their document; and the driver's frozen shape (four takes, one allowed carrier).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import p037_cumulative_evidence as cumulative  # noqa: E402

_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"ok[{name}]")
    else:
        _failures.append(name)
        print(f"FAIL[{name}]: {detail}")


def run() -> int:
    check("cumulative-evidence-selftest", cumulative.selftest() == 0, "see the FAIL lines above")
    check("four-governed-takes",
          [t[0] for t in cumulative.TAKES]
          == ["mos-repo", "mos-corpus", "verdict-python", "verdict-rust"],
          f"{[t[0] for t in cumulative.TAKES]}")
    check("allowed-surface-is-the-orphan-carrier-only",
          set(cumulative.ALLOWED_TOP_LEVEL_ADDED) == {"guarded_functions"},
          f"{sorted(cumulative.ALLOWED_TOP_LEVEL_ADDED)}")
    check("three-layers-two-engines",
          cumulative.LAYERS == ("lowered", "summaries", "verdicts")
          and cumulative.ENGINES == ("python", "rust"),
          f"{cumulative.LAYERS} {cumulative.ENGINES}")
    check("every-measurement-module-named",
          set(cumulative.MEASUREMENT_MODULES) == {"p037_evidence", "p037_mos_snapshot",
                                                   "p037_verdict_snapshot", "shadow_compare",
                                                   "ownlang", "ownlang.repro"},
          f"{sorted(cumulative.MEASUREMENT_MODULES)}")
    # The one-command invariant, the transaction and the driver pin are functions the
    # selftest exercises with real temporary checkouts and directories; here their
    # existence and the evidence-mode rule are pinned by name.
    try:
        cumulative.validate_stage("evidence", "takes")
        check("evidence-refuses-a-staged-run", False, "no refusal")
    except cumulative.Refused:
        check("evidence-refuses-a-staged-run", True)
    check("driver-pin-and-transaction-exist",
          callable(cumulative.require_reviewed_driver)
          and callable(cumulative.publish_transactionally)
          and callable(cumulative.driver_identity))
    check("orchestrator-pin-and-checkout-authentication-exist",
          callable(cumulative.require_orchestrator_commit)
          and callable(cumulative.authenticate_checkout))
    try:
        cumulative.require_orchestrator_commit({"commit": "a" * 40}, "b" * 40)
        check("orchestrator-commit-is-an-argument", False, "mismatch not refused")
    except cumulative.Refused:
        check("orchestrator-commit-is-an-argument", True)
    if _failures:
        print(f"RESULT: {len(_failures)} cumulative-evidence check(s) failed")
        return 1
    print("RESULT: cumulative-evidence driver controls hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
