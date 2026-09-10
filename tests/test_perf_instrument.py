#!/usr/bin/env python3
"""#263-A — controls for the measurement instrument itself.

The instrument's job is to produce numbers nobody can argue with later. These
controls check the properties that make that possible, and they check them by
exercising the mechanism rather than by reading its comments:

    perf-firewall-decisive     a decisive workload cannot reach a clock pre-D7
    perf-firewall-calibration  a calibration workload can (or the instrument is inert)
    perf-gate-dormant          the C1/C2 gate exists, is unarmed, and fails closed
    perf-gate-arms-by-data     arming needs committed data, never a source patch
    perf-gate-payload-identity a damaged D7 freeze arms nothing, for its own reason
    perf-session-drift         a candidate that changes refuses the rest of the session
    perf-notary-outside        no digest is computed inside a measured interval
    perf-provenance-complete   every §9 field is present on a produced report
    perf-no-engine-comparison  the instrument emits no engine-comparison statistic
    perf-smoke-untimed         decisive smoke carries no timing slot at all
    perf-phase-attribution     no interval claims to be a phase it merely contains
    perf-rung-outcome          a cell is timed only if the invocation did the work
    perf-digest-platform-stable the harness identity is content, not the checkout

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
            # The exact shape the old verifier armed on. It is refused here for
            # not declaring itself a freeze at all; that it ALSO carries the
            # wrong identity is checked, against a real committed freeze, by
            # perf-gate-payload-identity — one control per reason, so neither
            # passes on the other's behalf.
            pb.ATTESTATION.write_text(json.dumps({
                "harness_digest": pb.harness_digest(),
                "workload_manifest_sha256": digest,
                "python_reference_commit": "",
            }), encoding="utf-8")
            try:
                pb.IdentityGate.load(digest, "")
            except pb.InstrumentError as e:
                if "does not declare itself" not in str(e):
                    problems.append(f"a bare identity echo was refused by the wrong check: {e}")
            else:
                problems.append("a file echoing three computable values back was accepted as a "
                                "D7 freeze")
        finally:
            pb.ATTESTATION = saved

    if problems:
        fail("perf-gate-dormant", "; ".join(problems))
    else:
        ok("perf-gate-dormant", "the gate observes harness, manifest and reference identity, "
                                "is unarmed, and refuses both an unreadable file and a bare "
                                "identity echo")


# --- the C1/C2 freeze, built for real in a throwaway repository -------------


def _git(repo: Path, *args: str) -> str:
    import subprocess
    r = subprocess.run(["git", "-c", "user.email=c@example.invalid", "-c", "user.name=control",
                        *args], cwd=str(repo), capture_output=True, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.decode('utf-8', 'replace')}")
    return r.stdout.decode("utf-8", "replace").strip()


def _valid_payload(c1: dict) -> dict:
    payload = {
        "kind": pb.ATTESTATION_KIND,
        "schema": pb.ATTESTATION_SCHEMA,
        "c1": dict(c1),
        # Placeholders. The gate must never read a C2 VALUE, so what is written
        # here is deliberately not a plausible threshold.
        "c2": dict.fromkeys(pb.ATTESTATION_C2_KEYS, "<frozen by D7, never read by the gate>"),
    }
    payload["payload_sha256"] = pb.attestation_body_sha256(payload)
    return payload


def _build_freeze(repo: Path, c1: dict, break_: str = "") -> None:
    """A real payload + ratification, committed in a real repository.

    Each ``break_`` damages exactly ONE property, so a refusal can be matched
    against the check that was supposed to catch it. A control where every
    broken input is refused by the same over-broad check proves nothing about
    the other checks.
    """
    # NESTED, exactly as production stores them. The first version of these
    # fixtures put both objects at the repository ROOT, where the verifier's
    # wrong model — treating the file's own directory as the repository — is
    # accidentally right. Every control agreed while no real freeze could ever
    # have armed, because `<rev>:<path>` resolves from the tree root and the
    # verifier was asking for a bare basename.
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    nest = repo / "docs" / "evidence"
    nest.mkdir(parents=True, exist_ok=True)
    att = nest / pb.ATTESTATION.name
    rat = nest / pb.RATIFICATION.name
    att_rel = f"docs/evidence/{att.name}"

    payload = _valid_payload(c1)
    if break_ == "echo":
        payload = dict(c1)                                   # the defect this repair removes
    elif break_ == "no-c1":
        payload.pop("c1")
    elif break_ == "no-c2":
        payload.pop("c2")
    elif break_ == "partial-c1":
        payload["c1"] = {pb.ATTESTATION_C1_KEYS[0]: c1[pb.ATTESTATION_C1_KEYS[0]]}
    elif break_ == "partial-c2":
        payload["c2"] = {pb.ATTESTATION_C2_KEYS[0]: "only one of them"}
    elif break_ == "body-hash":
        payload["payload_sha256"] = "0" * 64
    elif break_ == "c1-mismatch":
        payload["c1"]["harness_digest"] = "f" * 64
        payload["payload_sha256"] = pb.attestation_body_sha256(
            {k: v for k, v in payload.items() if k != "payload_sha256"})

    att.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "freeze payload")
    commit = _git(repo, "rev-parse", "HEAD")

    if break_ == "no-ratification":
        return

    body = pb.attestation_body_sha256(payload) if "payload_sha256" in payload else "0" * 64
    ratification = {
        "kind": pb.RATIFICATION_KIND,
        "schema": pb.ATTESTATION_SCHEMA,
        "owner": "the owner",
        "payload_path": att_rel,
        "payload_commit_sha": commit,
        "ratified_payload_sha256": body,
        "signature": "none",
    }
    if break_ == "basename-path":
        # The exact shape the broken verifier would have accepted, and the shape
        # a real repository never has.
        ratification["payload_path"] = att.name
    elif break_ == "other-path":
        ratification["payload_path"] = "docs/evidence/some-other-file.json"
    elif break_ == "signed":
        ratification["signature"] = {"key_id": "DEADBEEFCAFE"}
    if break_ == "ratifies-other":
        ratification["ratified_payload_sha256"] = "a" * 64
    elif break_ == "bad-commit":
        ratification["payload_commit_sha"] = "0" * 40
    elif break_ == "signature-undeclared":
        ratification["signature"] = ""

    rat.write_text(json.dumps(ratification, indent=2) + "\n", encoding="utf-8")
    if break_ == "ratification-uncommitted":
        return
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "ratify the freeze")

    if break_ == "reformatted":
        # The one damage that reaches the blob check and nothing else: canonical
        # JSON is indentation-blind, so the body hash, C1 and the ratification
        # all still agree. Only git object identity can tell that the reviewed
        # bytes were replaced. If this case is accepted, the blob check is
        # decorative.
        att.write_text(json.dumps(payload, indent=4) + "\n", encoding="utf-8")


def _with_freeze(repo: Path, fn):
    saved_a, saved_r = pb.ATTESTATION, pb.RATIFICATION
    try:
        pb.ATTESTATION = repo / "docs" / "evidence" / pb.ATTESTATION.name
        pb.RATIFICATION = repo / "docs" / "evidence" / pb.RATIFICATION.name
        return fn()
    finally:
        pb.ATTESTATION, pb.RATIFICATION = saved_a, saved_r


# Each damaged freeze, and the phrase the check that owns it must produce.
# Matching the catcher is the point: without it, one broad refusal masquerades
# as ten working checks.
_BROKEN_FREEZES = (
    ("echo", "does not declare itself"),
    ("no-c1", "incomplete, missing: c1"),
    ("no-c2", "incomplete, missing: c2"),
    ("partial-c1", "no complete C1 section"),
    ("partial-c2", "no complete C2 section"),
    ("body-hash", "does not hash to its own payload_sha256"),
    ("c1-mismatch", "does not describe this instrument"),
    ("no-ratification", "unratified payload is a draft"),
    ("ratifies-other", "for a different payload"),
    ("bad-commit", "not a commit in this repository"),
    ("ratification-uncommitted", "not committed in this repository"),
    ("reformatted", "modified after it was frozen"),
    ("signature-undeclared", 'signature field must be exactly "none"'),
    ("basename-path", "may not choose which file it is about"),
    ("other-path", "may not choose which file it is about"),
    ("signed", "Signed ratification is not part of the accepted contract"),
)


def control_gate_payload_identity() -> None:
    """The gate verifies a D7 FREEZE, not a file that echoes computable values.

    The defect this replaces armed on any JSON carrying three values every
    holder of this repository can compute in one line — it proved the instrument
    was the instrument and called that a freeze. Each case below damages exactly
    one property of a real committed freeze and requires the refusal to name the
    check that owns it.
    """
    _, digest = pb.load_manifest()
    c1 = {"harness_digest": pb.harness_digest(), "workload_manifest_sha256": digest,
          "python_reference_commit": ""}
    problems = []
    for break_, expected in _BROKEN_FREEZES:
        with tempfile.TemporaryDirectory(prefix=f"perf-freeze-{break_}-") as td:
            repo = Path(td) / "repo"
            try:
                _build_freeze(repo, c1, break_)
            except RuntimeError as e:               # git itself unavailable
                problems.append(f"{break_}: could not build the fixture ({e})")
                continue

            def run():
                return pb.IdentityGate.load(digest, "")
            try:
                gate = _with_freeze(repo, run)
            except pb.InstrumentError as e:
                if expected not in str(e):
                    problems.append(f"{break_}: refused, but by the wrong check — expected "
                                    f"{expected!r}, got {str(e)[:140]!r}")
            else:
                if gate.armed:
                    problems.append(f"{break_}: a damaged D7 freeze ARMED the gate; the check "
                                    f"that should have said {expected!r} is not there")
                else:
                    problems.append(f"{break_}: neither armed nor refused — the gate went "
                                    "dormant on a payload that exists, which hides the damage")
    if problems:
        fail("perf-gate-payload-identity", "; ".join(problems))
    else:
        ok("perf-gate-payload-identity",
           f"{len(_BROKEN_FREEZES)} damaged freezes, each refused by the check that owns it "
           "(kind, C1, C2, body hash, instrument match, ratification, commit, blob, signature)")


def control_gate_arms_by_data() -> None:
    """Arming is DATA, not a patch — and the harness digest does not move.

    This is the obligation that stops #263-B from being a different instrument:
    if arming changed the digest D7 froze, the freeze would be void the moment
    it was used. The freeze here is REAL — committed objects in a throwaway
    repository — because a fixture the production checks cannot see is not
    evidence that the production checks pass.
    """
    workloads, digest = pb.load_manifest()
    before = pb.harness_digest()
    c1 = {"harness_digest": before, "workload_manifest_sha256": digest,
          "python_reference_commit": ""}
    problems = []
    with tempfile.TemporaryDirectory(prefix="perf-arm-") as td:
        repo = Path(td) / "repo"
        try:
            _build_freeze(repo, c1)
        except RuntimeError as e:
            fail("perf-gate-arms-by-data", f"could not build a real freeze fixture: {e}")
            return

        def run():
            gate = pb.IdentityGate.load(digest, "")
            after = pb.harness_digest()
            return gate, after

        try:
            gate, after = _with_freeze(repo, run)
        except pb.InstrumentError as e:
            fail("perf-gate-arms-by-data", f"a VALID committed freeze was refused: {e}")
            return

        if not gate.armed:
            problems.append("a valid freeze did not arm the gate, so #263-B could never run")
        if after != before:
            problems.append(f"arming moved the harness digest ({before[:12]} -> {after[:12]}): "
                            "the armed instrument is a different instrument")
        # Presence of C2, never its values: an armed gate must not become the
        # channel that carries a threshold into a #263-A artifact.
        leaked = [k for k, v in gate.pinned.items() if k.startswith("c2") and "never read" in v]
        if leaked:
            problems.append(f"the gate recorded C2 VALUES, not just field names: {leaked}")
        if gate.pinned.get("c2_fields_present") != ", ".join(sorted(pb.ATTESTATION_C2_KEYS)):
            problems.append("the gate did not record which C2 fields were present")
        if "unsigned" not in gate.pinned.get("signature", ""):
            problems.append("an unsigned freeze did not record itself as unsigned, so the report "
                            "would imply more authority than the freeze carried")
        # And with the gate armed, the firewall must let a decisive workload through.
        h = _harness(Path(td), gate)
        dec = next(w for w in workloads if w.decisive)
        try:
            h._assert_may_time(dec)
        except pb.FirewallBreach:
            problems.append("the gate armed but the firewall still refused: the gate would have "
                            "no effect at #263-B")
    if problems:
        fail("perf-gate-arms-by-data", "; ".join(problems))
    else:
        ok("perf-gate-arms-by-data", "two committed JSON objects arm the gate with no source "
                                     "patch, the harness digest is unchanged by arming, no C2 "
                                     "value is recorded, and the firewall then opens")


# --- phase attribution ------------------------------------------------------


def control_phase_attribution() -> None:
    """No interval claims to be a phase it merely contains.

    The floor rung is a usage error: the process starts, parses argv, writes a
    refusal and exits. Calling that interval `direct` startup would let a later
    subtraction hand D7 a phase nobody measured — the interval contains argv
    handling and refusal rendering, and the production surface cannot separate
    them without instrumentation #263-A is not authorized to add.
    """
    # A refusal phase belongs to exactly the rung whose outcome PROVES that
    # refusal happened. Without this the schema stayed internally consistent
    # while saying something false: one bundled "argv parsing + usage refusal"
    # phase sat on three rungs that never write a usage refusal, the report
    # copied the same taxonomy faithfully, and a control that only compared the
    # two agreed they matched. Two identical tables are not evidence; they are
    # one claim written twice.
    refusal_phase_evidence = {
        "cli-usage-refusal": "usage-help",
        "ownir-door-refusal": "door-refusal",
    }
    problems = []
    for r in pb.RUNGS:
        for phase, required in refusal_phase_evidence.items():
            if phase in r.phases and r.evidence != required:
                problems.append(f"{r.id}: claims {phase!r} but its outcome is proved by "
                                f"{r.evidence!r}, which demonstrates no such refusal happened")
            if r.evidence == required and phase not in r.phases:
                problems.append(f"{r.id}: its outcome proves {required!r}, so the interval "
                                f"contains {phase!r} and must name it")
        # Stated separately as well as implied, because this is the exact shape
        # the defect took: a refusal phase riding along on a successful rung.
        if r.evidence.startswith("verdict") and any(p.endswith("-refusal") for p in r.phases):
            problems.append(f"{r.id}: reaches a verdict, so no refusal phase belongs in it: "
                            f"{[p for p in r.phases if p.endswith('-refusal')]}")
        undeclared = [p for p in r.phases if p not in pb.PHASES]
        if undeclared:
            problems.append(f"{r.id}: names phases absent from the vocabulary: {undeclared}")
        if r.observability not in ("direct", "composed", "unavailable"):
            problems.append(f"{r.id}: unknown observability {r.observability!r}")
        if r.observability == "direct" and len(r.phases) != 1:
            problems.append(f"{r.id}: claims a DIRECT measurement of {len(r.phases)} phases; a "
                            "composed interval is not a direct one")
        if r.observability == "composed" and len(r.phases) < 2:
            problems.append(f"{r.id}: labelled composed but names {len(r.phases)} phase(s)")
        # The floor: a core invocation that takes no input still runs the CLI
        # front door, so it must say so.
        # Every real core invocation parses argv, floor or not.
        if r.surface == "core" and "cli-argv-parse" not in r.phases:
            problems.append(f"{r.id}: a core invocation always parses argv but does not name "
                            "that phase")
        if r.surface == "core" and r.needs == "none":
            if "cli-usage-refusal" not in r.phases:
                problems.append(f"{r.id}: the smallest core invocation writes a usage refusal "
                                "but does not name that phase")
            if r.observability == "direct":
                problems.append(f"{r.id}: the ladder floor is a LOWER BOUND on startup, not "
                                "startup measured directly")
    unused = sorted(set(pb.PHASES) - {p for r in pb.RUNGS for p in r.phases})
    if unused:
        problems.append(f"phases declared but measured by no rung: {unused}")

    # The shipped evidence must agree with the shipped rung table. This is what
    # makes "re-record after changing a rung" a gate rather than a promise.
    report = ROOT / "docs/evidence/p022-263a-calibration.linux.json"
    if not report.is_file():
        problems.append(f"{report.name} is missing: the calibration evidence cannot be checked "
                        "against the rung table it claims to describe")
    else:
        rep = json.loads(report.read_text(encoding="utf-8"))
        by_id = {r.id: r for r in pb.RUNGS}
        shipped_rungs = [{"id": r.id, "surface": r.surface, "phases": list(r.phases),
                          "observability": r.observability, "expect_rc": list(r.expect_rc),
                          "evidence": r.evidence, "why": r.why} for r in pb.RUNGS]
        if rep.get("rungs") != shipped_rungs:
            problems.append(f"{report.name} records a different rung table than the instrument "
                            "now defines (ids, phases, expected exit codes or evidence have "
                            "moved): the report predates the instrument and must be re-recorded")
        if rep.get("phases") != pb.PHASES:
            problems.append(f"{report.name} records a different phase vocabulary than the "
                            "instrument now defines: the report predates the rung table and "
                            "must be re-recorded")
        for cell in rep.get("cells", []):
            rung = by_id.get(str(cell.get("rung")))
            if rung is None:
                problems.append(f"{report.name}: cell names unknown rung {cell.get('rung')!r}")
                continue
            if list(cell.get("phases", [])) != list(rung.phases):
                problems.append(f"{report.name}: a {rung.id} cell claims phases "
                                f"{cell.get('phases')} but the rung names {list(rung.phases)}")
                break
            if cell.get("observability") != rung.observability:
                problems.append(f"{report.name}: a {rung.id} cell claims "
                                f"{cell.get('observability')!r} observability but the rung is "
                                f"{rung.observability!r}")
                break
    if problems:
        fail("perf-phase-attribution", "; ".join(problems))
    else:
        ok("perf-phase-attribution", "every rung's phases are declared, a refusal phase "
                                     "appears only where the outcome proves that refusal, the "
                                     "ladder floor is a bound rather than startup, and the "
                                     "shipped report agrees with the rung table")

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
    calls = {"n": 0, "git": 0}
    real = pb.sha256_file
    real_git = pb._git_in

    def counting(path: Path) -> tuple[str, int]:
        calls["n"] += 1
        return real(path)

    # The gate now shells out to git for blob identity, so obligation (c) has a
    # second way to be violated: a verifier that pays for itself out of the
    # startup benchmark is a defect whether it spends the time hashing or
    # forking.
    def counting_git(repo, *args):
        calls["git"] += 1
        return real_git(repo, *args)

    with tempfile.TemporaryDirectory(prefix="perf-notary-") as td:
        tmp = Path(td)
        _, digest = pb.load_manifest()
        h = _harness(tmp, pb.IdentityGate.load(digest, ""))
        argv = [sys.executable, "-c", "pass"]
        pb.sha256_file = counting        # type: ignore[assignment]
        pb._git_in = counting_git        # type: ignore[assignment]
        try:
            h._run_once(argv, dict(os.environ), ROOT)
        finally:
            pb.sha256_file = real        # type: ignore[assignment]
            pb._git_in = real_git        # type: ignore[assignment]
    if calls["n"]:
        problems.append(f"{calls['n']} digest(s) were computed inside the measured interval — "
                        "the notary is billing the benchmark for its own work")
    if calls["git"]:
        problems.append(f"{calls['git']} git invocation(s) ran inside the measured interval — "
                        "identity verification is billing the benchmark for its own work")
    if problems:
        fail("perf-notary-outside", "; ".join(problems))
    else:
        ok("perf-notary-outside", "a measured interval computes no digests and forks no git; "
                                  "identity is verified before the clock starts")


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
        # Presence is not agreement. A report can carry a harness digest and a
        # manifest digest that belong to some earlier tree and still tick every
        # "field is present" box, which makes it a receipt rather than evidence.
        if rep.get("harness", {}).get("digest") != pb.harness_digest():
            problems.append(
                f"{path.name}: records harness digest "
                f"{str(rep.get('harness', {}).get('digest'))[:12]} but the shipped instrument is "
                f"{pb.harness_digest()[:12]} — it certifies a tree that is no longer here and "
                "must be re-recorded")
        if rep.get("provenance", {}).get("workload_manifest_sha256") != pb.load_manifest()[1]:
            problems.append(f"{path.name}: records a workload manifest digest that is not the "
                            "shipped manifest's")
        if not (rep.get("outcomes") or {}).get("valid"):
            problems.append(f"{path.name}: was recorded with cells whose invocation did not do "
                            "the rung's work")
        # CI legs may record "this environment is not measurement-grade" — that
        # is a true statement about a hosted runner and not a defect. COMMITTED
        # evidence may not: a report that ships as the calibration of record has
        # to come from a machine that reproduced itself, on both counts.
        repro = rep.get("reproducibility")
        if repro is None:
            problems.append(f"{path.name}: ships with no reproducibility check, so nothing says "
                            "a second run on that machine agreed with it")
        elif not repro.get("reproduced"):
            problems.append(
                f"{path.name}: ships as the calibration of record but did not reproduce "
                f"(outcomes {repro.get('outcomes_reproduced')}, timings "
                f"{repro.get('timings_reproduced')}): "
                f"{repro.get('cells_outside_tolerance')}{repro.get('cells_whose_outcome_changed')}")
        # All three axes, checked on the shipped artifact rather than inferred.
        adm = rep.get("admissibility") or {}
        for axis in ("outcomes_reproduced", "timings_reproduced", "environment_valid"):
            if not adm.get(axis):
                problems.append(f"{path.name}: ships as the calibration of record with "
                                f"{axis}={adm.get(axis)!r}; a report of record needs all three")
        if not adm.get("admissible"):
            problems.append(f"{path.name}: is not marked admissible")

        # WARMUP is not a sizing knob. It moved from 2 to 3 alongside a
        # repetitions escalation that had been authorised on its own, which
        # turned one permitted knob into two turned after seeing which runs went
        # red. Repetitions may differ from the default (that is the sanctioned
        # escalation); warmup may not.
        # A report of record names the tree it measured. With a dirty tree that
        # sha names something other than what was on disk, so it names nothing.
        # Both halves are held to it: run A written into the working tree before
        # run B measures is exactly how a pair acquires dirty provenance.
        if (rep.get("provenance") or {}).get("tree_dirty"):
            problems.append(f"{path.name}: recorded on a DIRTY tree, so its tree_sha does not "
                            "identify what was measured")
        warm = (rep.get("harness") or {}).get("warmup_discards")
        if warm != pb.DEFAULT_WARMUP_DISCARDS:
            problems.append(f"{path.name}: recorded with warmup_discards={warm}, but the policy "
                            f"default is {pb.DEFAULT_WARMUP_DISCARDS}. Warmup is not a sizing "
                            "knob; changing it is a deliberate policy edit, not a flag")

        # BOTH halves of the pair, or "reproduced" cannot be recomputed from
        # committed evidence — only the program that already reached the verdict
        # would know run A's numbers.
        earlier = (repro or {}).get("earlier_run") or {}
        if not earlier.get("path") or not earlier.get("sha256"):
            problems.append(f"{path.name}: names no earlier run, so its reproducibility verdict "
                            "rests on data that was never committed")
        else:
            mate = path.parent / str(earlier["path"])
            if not mate.is_file():
                problems.append(f"{path.name}: names earlier run {earlier['path']!r}, which is "
                                "not committed beside it")
            else:
                got = pb.sha256_bytes(mate.read_bytes())
                if got != earlier["sha256"]:
                    problems.append(f"{path.name}: the committed {earlier['path']} hashes "
                                    f"{got[:12]} but the verdict was computed against "
                                    f"{str(earlier['sha256'])[:12]}")
                if earlier.get("tree_dirty"):
                    problems.append(f"{path.name}: its earlier run was recorded on a dirty tree")
                for field in ("harness_digest", "calibration_repetitions", "warmup_discards"):
                    a = earlier.get(field)
                    b = ((rep.get("harness") or {}).get("digest") if field == "harness_digest"
                         else (rep.get("harness") or {}).get(field))
                    if a != b:
                        problems.append(f"{path.name}: run A and run B disagree on {field} "
                                        f"({a!r} vs {b!r}); a pair measured under different "
                                        "settings is not a reproducibility check")
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
           f"{len(committed)} committed calibration report(s) carry every §9 field, name the "
           "SHIPPED harness and manifest digests, retain raw per-iteration data, carry only "
           "valid-outcome cells, and were taken with the gate dormant")


# --- rung outcomes ----------------------------------------------------------


def control_rung_outcome() -> None:
    """A cell is a measurement only if the invocation did the rung's work.

    The instrument once timed twelve command-not-found exits and reported them
    as reproduced: with no .NET on PATH the launcher rungs died at 127 before
    running anything, and nothing looked at the exit code. Both directions are
    checked here, because a contract that refuses everything is not a contract,
    it is a broken instrument that happens to be safe.
    """
    problems = []
    _, digest = pb.load_manifest()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)

    # Structural: no rung may declare command-not-found a success, and every
    # rung must name codes and an evidence kind the checker knows.
    for r in pb.RUNGS:
        if not r.expect_rc:
            problems.append(f"{r.id}: declares no expected exit code, so any exit would pass")
        if 127 in r.expect_rc:
            problems.append(f"{r.id}: declares 127 (command-not-found) as doing its job")
        try:
            pb._evidence_problem(r.evidence, "ownir", "")
        except pb.InstrumentError:
            problems.append(f"{r.id}: names evidence kind {r.evidence!r} the checker cannot check")
    try:
        pb._evidence_problem("no-such-evidence", "", "")
    except pb.InstrumentError:
        pass
    else:
        problems.append("an unknown evidence kind was silently accepted")

    with tempfile.TemporaryDirectory(prefix="perf-outcome-") as td:
        h = _harness(Path(td), pb.IdentityGate.load(digest, ""))
        launcher = next(r for r in pb.RUNGS if r.surface == "launcher")
        # Exactly the shape an absent toolchain produced.
        bad = h.verify_outcome(launcher, [sys.executable, "-c", "raise SystemExit(127)"],
                               env, ROOT)
        if bad["valid"]:
            problems.append("a 127 exit was accepted as a launcher measurement — the defect that "
                            "let 12 command-not-found cells be reported as reproduced")
        elif not any("127" in str(x) for x in bad["problems"]):
            problems.append("the refusal does not name the command-not-found exit")

        # A process that exits on a DECLARED code but produced no verdict is
        # still not a measurement: the exit code alone is not the contract.
        silent = h.verify_outcome(launcher, [sys.executable, "-c", "pass"], env, ROOT)
        if silent["valid"]:
            problems.append("an invocation that exited 0 with no verdict was accepted; the "
                            "evidence check is doing nothing")

        # And the healthy direction, on the real production surface.
        floor = next(r for r in pb.RUNGS if r.needs == "none")
        good = h.verify_outcome(floor, [sys.executable, "-m", "ownlang", "ownir"], env, ROOT)
        if not good["valid"]:
            problems.append(f"the real floor invocation was refused: {good['problems']}")

    if problems:
        fail("perf-rung-outcome", "; ".join(problems))
    else:
        ok("perf-rung-outcome", "every rung declares exit codes and checkable evidence, 127 is "
                                "never success, a silent zero-exit is refused, and the real "
                                "production floor invocation is accepted")


def control_digest_platform_stable() -> None:
    """The instrument's identity is its CONTENT, not the checkout it arrived in.

    D7's C1 freezes the harness digest and #263-B runs on both platforms, so a
    digest that moves with line endings would arm a freeze on one platform and
    refuse it on the other. It did: the same tree hashed af32f04ddbad on Linux
    and 51ef2ca2422a on a Windows runner, where core.autocrlf rewrote the
    instrument source on checkout. Nothing in the harness noticed until a
    control compared the shipped report's digest against the running one.
    """
    problems = []
    with tempfile.TemporaryDirectory(prefix="perf-eol-") as td:
        lf = Path(td) / "lf.py"
        crlf = Path(td) / "crlf.py"
        body = "one\ntwo\nthree\n"
        lf.write_bytes(body.encode())
        crlf.write_bytes(body.replace("\n", "\r\n").encode())

        if pb.sha256_text_file(lf)[0] != pb.sha256_text_file(crlf)[0]:
            problems.append("the text digest still moves with line endings, so the same "
                            "instrument has two identities and a frozen C1 fits only one "
                            "of them")
        # And the raw hasher must stay raw: the candidate binary is bytes, and
        # a hasher that normalized them would be a different kind of wrong.
        if pb.sha256_file(lf)[0] == pb.sha256_file(crlf)[0]:
            problems.append("sha256_file normalized its input; the candidate binary's "
                            "identity must be its actual bytes")
        blob = Path(td) / "bin"
        blob.write_bytes(b"\x00\r\n\x01")
        if pb.sha256_file(blob)[0] != pb.sha256_bytes(b"\x00\r\n\x01"):
            problems.append("sha256_file does not hash a binary verbatim")
    if problems:
        fail("perf-digest-platform-stable", "; ".join(problems))
    else:
        ok("perf-digest-platform-stable", "the harness digest is content-addressed and "
                                          "survives a CRLF checkout, while the candidate "
                                          "binary is still hashed byte for byte")


def run() -> int:
    control_firewall()
    control_gate_dormant()
    control_gate_arms_by_data()
    control_gate_payload_identity()
    control_session_drift()
    control_notary_outside_interval()
    control_no_engine_comparison()
    control_smoke_untimed()
    control_provenance_complete()
    control_phase_attribution()
    control_rung_outcome()
    control_digest_platform_stable()
    print()
    print(f"perf instrument controls: {len(_PASSES)} passed, {len(_FAILURES)} failed")
    return 1 if _FAILURES else 0


if __name__ == "__main__":
    sys.exit(run())
