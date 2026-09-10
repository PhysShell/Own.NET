#!/usr/bin/env python3
"""#263-A — controls for the measurement instrument itself.

The instrument's job is to produce numbers nobody can argue with later. These
controls check the properties that make that possible, and they check them by
exercising the mechanism rather than by reading its comments:

    perf-firewall-decisive     a decisive workload cannot reach a clock pre-D7
    perf-firewall-calibration  a calibration workload can (or the instrument is inert)
    perf-gate-dormant          the C1/C2 gate exists, is unarmed, and fails closed
    perf-gate-arms-by-data     arming needs a JSON file, never a source patch
    perf-session-drift         a candidate that changes refuses the rest of the session
    perf-notary-outside        no digest is computed inside a measured interval
    perf-provenance-complete   every §9 field is present on a produced report
    perf-no-engine-comparison  the instrument emits no engine-comparison statistic
    perf-smoke-untimed         decisive smoke carries no timing slot at all

Failures print `FAIL[<check>]: <detail>`; nothing stops at the first one.

Run:  python tests/test_perf_instrument.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import perf_baseline as pb  # noqa: E402

_FAILURES: list[tuple[str, str]] = []
_PASSES: list[str] = []


def fail(check: str, detail: str) -> None:
    _FAILURES.append((check, detail))
    print(f"FAIL[{check}]: {detail}")


def ok(check: str, detail: str = "") -> None:
    _PASSES.append(check)
    print(f"ok[{check}]: {detail}" if detail else f"ok[{check}]")


def _harness(tmp: Path, gate: pb.IdentityGate, candidate: Path | None = None) -> pb.Harness:
    cand = candidate or (tmp / "fake-candidate")
    if not cand.exists():
        cand.write_bytes(b"not a real binary, but it has an identity\n")
    return pb.Harness(gate=gate, session=pb.SessionIdentity.freeze(cand), rss=pb.RssProbe(),
                      tmp=tmp, candidate=cand, warmup_discards=0, repetitions=1, seed=1)


# --- the firewall ----------------------------------------------------------


def control_firewall() -> None:
    """No decisive workload reaches a clock while the gate is unarmed.

    Both directions, because a firewall that refuses everything is not a
    firewall, it is a broken instrument that happens to be safe.
    """
    workloads, digest = pb.load_manifest()
    gate = pb.IdentityGate.load(digest, "")
    decisive_admitted, calibration_refused = [], []
    with tempfile.TemporaryDirectory(prefix="perf-fw-") as td:
        h = _harness(Path(td), gate)
        for w in workloads:
            try:
                h._assert_may_time(w)
            except pb.FirewallBreach:
                if not w.decisive:
                    calibration_refused.append(w.id)
            else:
                if w.decisive:
                    decisive_admitted.append(w.id)
    if decisive_admitted:
        fail("perf-firewall-decisive",
             f"the timed path admitted decisive workloads with the gate unarmed: "
             f"{decisive_admitted}")
    else:
        ok("perf-firewall-decisive",
           f"all {sum(1 for w in workloads if w.decisive)} decisive workloads are refused a clock "
           "while the D7 gate is dormant")
    if calibration_refused:
        fail("perf-firewall-calibration",
             f"calibration workloads were refused too, so the firewall proves nothing about the "
             f"decisive ones: {calibration_refused}")
    else:
        ok("perf-firewall-calibration",
           f"all {sum(1 for w in workloads if not w.decisive)} calibration workloads are admitted "
           "— the refusal above is selective, not blanket")


# --- the two identity domains ----------------------------------------------


def control_gate_dormant() -> None:
    """The gate is present and unarmed, and a malformed attestation fails CLOSED."""
    _, digest = pb.load_manifest()
    gate = pb.IdentityGate.load(digest, "")
    problems = []
    if gate.armed:
        problems.append("the gate is ARMED — #263-A must never ship a D7 attestation")
    if "harness_digest" not in gate.observed:
        problems.append("the gate observes no harness identity, so C1 would have nothing to pin")
    for key in ("workload_manifest_sha256", "python_reference_commit"):
        if key not in gate.observed:
            problems.append(f"the gate observes no {key}")

    saved = pb.ATTESTATION
    with tempfile.TemporaryDirectory(prefix="perf-gate-") as td:
        try:
            pb.ATTESTATION = Path(td) / "att.json"
            pb.ATTESTATION.write_text("{ this is not json", encoding="utf-8")
            try:
                pb.IdentityGate.load(digest, "")
            except pb.InstrumentError:
                pass
            else:
                problems.append("an unreadable attestation did not fail closed")
            pb.ATTESTATION.write_text(json.dumps({"harness_digest": "wrong"}), encoding="utf-8")
            try:
                pb.IdentityGate.load(digest, "")
            except pb.InstrumentError:
                pass
            else:
                problems.append("an attestation describing a different instrument was accepted")
        finally:
            pb.ATTESTATION = saved

    if problems:
        fail("perf-gate-dormant", "; ".join(problems))
    else:
        ok("perf-gate-dormant", "the gate observes harness, manifest and reference identity, is "
                                "unarmed, and refuses a malformed or mismatched attestation")


def control_gate_arms_by_data() -> None:
    """Arming is DATA, not a patch — and the harness digest does not move when it happens.

    This is the obligation that stops #263-B from being a different instrument:
    if arming changed the digest D7 froze, the freeze would be void the moment
    it was used.
    """
    _, digest = pb.load_manifest()
    before = pb.harness_digest()
    saved = pb.ATTESTATION
    problems = []
    with tempfile.TemporaryDirectory(prefix="perf-arm-") as td:
        try:
            pb.ATTESTATION = Path(td) / "att.json"
            pb.ATTESTATION.write_text(json.dumps({
                "harness_digest": before,
                "workload_manifest_sha256": digest,
                "python_reference_commit": "",
            }), encoding="utf-8")
            gate = pb.IdentityGate.load(digest, "")
            if not gate.armed:
                problems.append("a correct attestation did not arm the gate, so #263-B could "
                                "never run at all")
            after = pb.harness_digest()
            if after != before:
                problems.append(f"arming moved the harness digest ({before[:12]} -> {after[:12]}): "
                                "the armed instrument is a different instrument")
            # And with the gate armed, the firewall must let a decisive workload through.
            workloads, _ = pb.load_manifest()
            h = _harness(Path(td), gate)
            dec = next(w for w in workloads if w.decisive)
            try:
                h._assert_may_time(dec)
            except pb.FirewallBreach:
                problems.append("the gate armed but the firewall still refused: the gate would "
                                "have no effect at #263-B")
        finally:
            pb.ATTESTATION = saved
    if problems:
        fail("perf-gate-arms-by-data", "; ".join(problems))
    else:
        ok("perf-gate-arms-by-data", "a JSON attestation alone arms the gate, the harness digest "
                                     "is unchanged by arming, and the firewall then opens")


def control_session_drift() -> None:
    """A candidate that changes mid-session refuses the remainder."""
    problems = []
    with tempfile.TemporaryDirectory(prefix="perf-drift-") as td:
        cand = Path(td) / "candidate.bin"
        cand.write_bytes(b"binary A")
        session = pb.SessionIdentity.freeze(cand)
        try:
            session.reverify()
        except pb.InstrumentError as e:
            problems.append(f"an unchanged candidate was refused: {e}")
        cand.write_bytes(b"binary B, a different thing under test")
        session.measurements_taken = 7
        try:
            session.reverify()
        except pb.InstrumentError as e:
            if "7 measurement" not in str(e):
                problems.append("the refusal does not say how many cells were already measured "
                                "on the old binary")
        else:
            problems.append("the candidate changed and the session carried on: half the cells "
                            "would be measured on a different binary")
    if problems:
        fail("perf-session-drift", "; ".join(problems))
    else:
        ok("perf-session-drift", "candidate drift refuses the rest of the session and names how "
                                 "many measurements preceded it")


def control_notary_outside_interval() -> None:
    """No digest is computed inside a measured interval.

    Counted, not asserted: a gate that pays for itself out of the startup
    benchmark is a defect wearing a safeguard's coat, and the only way to know
    is to count the calls while the clock is running.
    """
    problems = []
    calls = {"n": 0}
    real = pb.sha256_file

    def counting(path: Path) -> tuple[str, int]:
        calls["n"] += 1
        return real(path)

    with tempfile.TemporaryDirectory(prefix="perf-notary-") as td:
        tmp = Path(td)
        _, digest = pb.load_manifest()
        h = _harness(tmp, pb.IdentityGate.load(digest, ""))
        argv = [sys.executable, "-c", "pass"]
        pb.sha256_file = counting  # type: ignore[assignment]
        try:
            h._run_once(argv, dict(os.environ), ROOT)
        finally:
            pb.sha256_file = real  # type: ignore[assignment]
    if calls["n"]:
        problems.append(f"{calls['n']} digest(s) were computed inside the measured interval — "
                        "the notary is billing the benchmark for its own work")
    if problems:
        fail("perf-notary-outside", "; ".join(problems))
    else:
        ok("perf-notary-outside", "a measured interval computes no digests; identity is verified "
                                  "before the clock starts")


# --- what the instrument emits ---------------------------------------------


def control_no_engine_comparison() -> None:
    """The instrument records each engine's own numbers and nothing derived from both."""
    problems = list(pb.engine_comparison_problems({
        "cells": [{"engine": "python", "timing": {"median_ns": 1}},
                  {"engine": "rust", "timing": {"median_ns": 2}}]}))
    if problems:
        problems = [f"a legitimate two-cell report was rejected: {problems}"]
    # And the other direction: a report that DID carry a comparison must be caught.
    if not pb.engine_comparison_problems({"summary": {"rust_vs_python_ratio": 0.5}}):
        problems.append("a report carrying an engine-comparison key was accepted")
    if not pb.engine_comparison_problems({"cells": [{"engine": "rust", "python_median_ns": 3}]}):
        problems.append("a cell carrying another engine's number was accepted")
    if problems:
        fail("perf-no-engine-comparison", "; ".join(problems))
    else:
        ok("perf-no-engine-comparison", "single-engine cells pass; a comparison key or a "
                                        "cross-engine cell is refused")


def control_smoke_untimed() -> None:
    """Decisive smoke carries no timing slot — not an empty one."""
    workloads, digest = pb.load_manifest()
    problems = []
    with tempfile.TemporaryDirectory(prefix="perf-smoke-") as td:
        h = _harness(Path(td), pb.IdentityGate.load(digest, ""))
        for w in workloads:
            if not w.decisive:
                continue
            row = h.smoke(w, ROOT / str(w.spec.get("path", "")))
            leaked = [k for k in row
                      if any(t in k for t in ("elapsed", "timing", "ns", "duration", "rss"))]
            if leaked:
                problems.append(f"{w.id}: smoke carries measurement keys {leaked}")
            if row.get("tag") != pb.CALIBRATION_ONLY:
                problems.append(f"{w.id}: smoke is untagged")
    if problems:
        fail("perf-smoke-untimed", "; ".join(problems))
    else:
        ok("perf-smoke-untimed", "decisive smoke reports availability and shape only, tagged "
                                 "CALIBRATION_ONLY, with no measurement slot to fill in later")


def control_provenance_complete() -> None:
    """Every field §9 requires is present on a produced report."""
    required = [
        ("provenance", "tree_sha"), ("provenance", "python_reference_commit"),
        ("provenance", "python_interpreter"), ("provenance", "workload_manifest_sha256"),
        ("provenance", "environment"), ("provenance", "timestamp_utc"),
        ("identity", "session_candidate"), ("harness", "seed"),
        ("harness", "execution_order"), ("harness", "digest"),
        ("noise", "before"), ("noise", "after"),
    ]
    committed = sorted(Path(ROOT / "docs/evidence").glob("p022-263a-calibration.*.json"))
    if not committed:
        ok("perf-provenance-complete", "no calibration report is committed yet; the shape is "
                                       "checked when one is")
        return
    problems = []
    for path in committed:
        rep = json.loads(path.read_text(encoding="utf-8"))
        if rep.get("tag") != pb.CALIBRATION_ONLY:
            problems.append(f"{path.name}: not tagged {pb.CALIBRATION_ONLY}")
        for outer, inner in required:
            if inner not in (rep.get(outer) or {}):
                problems.append(f"{path.name}: missing {outer}.{inner}")
        for i, cell in enumerate(rep.get("cells", [])):
            if not cell.get("raw_elapsed_ns"):
                problems.append(f"{path.name}: cell {i} kept no raw per-iteration data")
                break
        problems.extend(f"{path.name}: {p}" for p in pb.engine_comparison_problems(rep))
        if rep.get("identity", {}).get("gate_armed"):
            problems.append(f"{path.name}: recorded with the D7 gate ARMED")
    if problems:
        fail("perf-provenance-complete", "; ".join(problems))
    else:
        ok("perf-provenance-complete",
           f"{len(committed)} committed calibration report(s) carry every §9 field, retain raw "
           "per-iteration data, and were taken with the gate dormant")


def run() -> int:
    control_firewall()
    control_gate_dormant()
    control_gate_arms_by_data()
    control_session_drift()
    control_notary_outside_interval()
    control_no_engine_comparison()
    control_smoke_untimed()
    control_provenance_complete()
    print()
    print(f"perf instrument controls: {len(_PASSES)} passed, {len(_FAILURES)} failed")
    return 1 if _FAILURES else 0


if __name__ == "__main__":
    sys.exit(run())
