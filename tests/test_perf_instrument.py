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
    gate = pb.IdentityGate.load(digest)
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
    gate = pb.IdentityGate.load(digest)
    problems = []
    if gate.armed:
        problems.append("the gate is ARMED — #263-A must never ship a D7 attestation")
    if "harness_digest" not in gate.observed:
        problems.append("the gate observes no harness identity, so C1 would have nothing to pin")
    for key in ("workload_manifest_sha256", "python_reference_commit"):
        if key not in gate.observed:
            problems.append(f"the gate observes no {key}")

    saved = pb.D7_PAYLOAD
    with tempfile.TemporaryDirectory(prefix="perf-gate-") as td:
        try:
            pb.D7_PAYLOAD = Path(td) / "payload.json"
            pb.D7_PAYLOAD.write_text("{ this is not json", encoding="utf-8")
            try:
                pb.IdentityGate.load(digest)
            except pb.InstrumentError:
                pass
            else:
                problems.append("an unreadable D7 payload did not fail closed")
            # The exact shape an older verifier armed on: computable values
            # echoed back. It is refused here for not declaring itself a payload
            # at all; the full §6 machinery is checked, against a real two-commit
            # freeze, by perf-gate-payload-identity — one control per reason, so
            # neither passes on the other's behalf.
            pb.D7_PAYLOAD.write_text(json.dumps(
                pb.IdentityGate.observe(digest)), encoding="utf-8")
            try:
                pb.IdentityGate.load(digest)
            except pb.InstrumentError as e:
                if "does not declare itself a D7 payload" not in str(e):
                    problems.append(f"a bare identity echo was refused by the wrong check: {e}")
            else:
                problems.append("a file echoing computable values back was accepted as a D7 "
                                "freeze")
        finally:
            pb.D7_PAYLOAD = saved

    if problems:
        fail("perf-gate-dormant", "; ".join(problems))
    else:
        ok("perf-gate-dormant", "the gate observes instrument, reference and workload identity, "
                                "is unarmed, and refuses both an unreadable file and a bare "
                                "identity echo")


# --- the D7 freeze, built for real in a throwaway repository ----------------


def _git(repo: Path, *args: str) -> str:
    """git in a throwaway repository, with background housekeeping OFF.

    `git commit` normally spawns `gc --auto`, which keeps writing inside `.git`
    after the commit returns. When the fixture is then torn down, `rmtree` can
    race that process and die with "Directory not empty: .../.git" — which is
    exactly what CI hit on the added anchor fixtures, since they commit more
    often than the old ones did. The repository lives for one check and is
    deleted; it has nothing to gain from housekeeping and everything to lose
    from a background writer.
    """
    import subprocess
    r = subprocess.run(["git", "-c", "user.email=c@example.invalid", "-c", "user.name=control",
                        "-c", "gc.auto=0", "-c", "maintenance.auto=false",
                        *args], cwd=str(repo), capture_output=True, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.decode('utf-8', 'replace')}")
    return r.stdout.decode("utf-8", "replace").strip()


def _canonical(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _protocol_cell(phase: str, workload: str, platform: str, regime: str,
                   na: bool = False) -> dict:
    """One preregistered cell.

    Every value is a deliberately non-production placeholder. A fixture that
    only passed with plausible NUMBERS would be proving that the gate reads
    thresholds, which is the one thing it must never do. What is being checked
    is that the preregistration is STRUCTURALLY there.
    """
    dims = {"phase": phase, "workload_id": workload, "platform": platform, "regime": regime}
    if na:
        return {"dimensions": dims,
                "not_applicable": "<reason frozen by D7: no allocation counter here>"}
    return {
        "dimensions": dims,
        "bound": "<budget frozen by D7>",
        "pass_fail_rule": "<rule frozen by D7>",
        "inconclusive_band": "<band frozen by D7>",
        "repetition_ladder": dict.fromkeys(pb.D7_LADDER_KEYS, "<frozen by D7>"),
        "comparison_statistic": "<statistic frozen by D7>",
        "rss_policy": "<rss treatment frozen by D7>",
        "allocation_policy": "<allocation treatment frozen by D7>",
    }


def _valid_payload(observed: dict, anchor: str) -> dict:
    return {
        "kind": pb.D7_PAYLOAD_KIND,
        "schema": pb.D7_SCHEMA,
        "cells": {
            "core-full-sarif|rust|cal-facts-small|process-cold": _protocol_cell(
                "render-sarif", "cal-facts-small", "linux", "process-cold"),
            "core-usage|rust|cal-facts-tiny|warm": _protocol_cell(
                "process-startup-core", "cal-facts-tiny", "windows", "warm"),
            "core-full-human|python|cal-facts-small|process-cold": _protocol_cell(
                "render-human", "cal-facts-small", "linux", "process-cold", na=True),
        },
        "rollups": dict.fromkeys(pb.D7_ROLLUP_LEVELS, "<roll-up frozen by D7>"),
        pb.D7_PAYLOAD_ANCHOR: anchor,
        **{k: observed[k] for k in pb.D7_PAYLOAD_BINDING_KEYS},
        "ratification": {"owner": "the owner", "ratified_at": "2026-01-01T00:00:00Z",
                         "signature": "none"},
    }


def _seed_instrument(repo: Path) -> str:
    """Commit S — the accepted #263-A instrument, in a checkout of its own.

    The old fixture committed a README and two JSON files and took ``observed``
    from the REAL repository. So the one thing the production lifecycle does
    between acceptance and #263-B — move HEAD past S — could not happen here,
    and the gate's ``instrument_tree_sha = git rev-parse HEAD`` check compared
    the real repository's HEAD against a payload built from that same HEAD. The
    fixture isolated production from precisely the effect it existed to check.
    """
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    for src in pb.INSTRUMENT_SOURCES:
        dst = repo / pb._instrument_rel(src)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
    ref = repo / pb.PYTHON_REFERENCE_PATH / "reference.py"
    ref.parent.mkdir(parents=True, exist_ok=True)
    ref.write_text("# stands in for the Python reference source\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "S: the accepted #263-A instrument")
    return _git(repo, "rev-parse", "HEAD")


def _commit_file(repo: Path, rel: str, text: str, message: str) -> str:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _build_freeze(repo: Path, manifest_digest: str, break_: str = "") -> dict:
    """A real D7 lifecycle: S, ordinary work, C1, C2, then more ordinary work.

    Returns what the gate should observe in THIS repository. The commits after
    C2 are the point: at #263-B the repository has moved on, and a gate that
    demanded HEAD equal the accepted tree could never arm.

    Each ``break_`` damages exactly ONE property, so a refusal can be matched
    against the check that owns it. A control where every broken input is
    refused by the same over-broad check proves nothing about the other checks.
    """
    anchor = _seed_instrument(repo)
    nest = repo / "docs" / "evidence"
    pay = nest / pb.D7_PAYLOAD.name
    att = nest / pb.D7_ATTESTATION.name
    pay_rel = f"docs/evidence/{pay.name}"
    self_rel = pb._instrument_rel(pb.SELF)

    if break_ == "anchor-content-drift":
        # A commit that HAS the instrument sources and IS an ancestor of C1,
        # but whose instrument is not the one the freeze describes.
        real = (repo / self_rel).read_bytes()
        anchor = _commit_file(repo, self_rel, "# a different instrument\n", "drifted instrument")
        (repo / self_rel).write_bytes(real)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "restore the instrument")
    elif break_ in ("anchor-missing-sources", "anchor-not-ancestor"):
        # A commit off to the side, so it is not an ancestor of C1.
        head = _git(repo, "rev-parse", "HEAD")
        _git(repo, "checkout", "-q", "--orphan", "sidelined")
        _git(repo, "rm", "-rq", "--cached", ".")
        for stray in ("docs", "scripts", pb.PYTHON_REFERENCE_PATH):
            if (repo / stray).exists():
                import shutil
                shutil.rmtree(repo / stray)
        if break_ == "anchor-not-ancestor":
            # Same instrument content, so only ancestry can catch it.
            for src in pb.INSTRUMENT_SOURCES:
                dst = repo / pb._instrument_rel(src)
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(src.read_bytes())
        (repo / "unrelated").write_text("not the instrument\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "a commit that is not the accepted instrument")
        anchor = _git(repo, "rev-parse", "HEAD")
        _git(repo, "checkout", "-q", "-f", head)
        _git(repo, "checkout", "-q", "-B", "main")

    # Ordinary work between acceptance and the freeze, so S is never the tip.
    _commit_file(repo, "docs/notes/unrelated.md", "work after acceptance\n", "ordinary work")

    observed = pb.IdentityGate.observe(manifest_digest, repo)
    payload = _valid_payload(observed, anchor)

    if break_ == "echo":
        payload = {k: observed[k] for k in pb.D7_PAYLOAD_BINDING_KEYS}
    elif break_ == "payload-incomplete":
        payload.pop(pb.D7_PAYLOAD_PROTOCOL_KEYS[0])
    elif break_ == "no-ratification":
        payload["ratification"] = {"owner": "the owner"}
    elif break_ == "signed":
        payload["ratification"]["signature"] = {"key_id": "DEADBEEF"}
    elif break_ == "binding-mismatch":
        payload["harness_digest"] = "f" * 64
    elif break_ == "anchor-not-hex":
        payload[pb.D7_PAYLOAD_ANCHOR] = "the commit we all agreed on"
    elif break_ == "anchor-not-a-commit":
        payload[pb.D7_PAYLOAD_ANCHOR] = "0" * 40
    elif break_ == "proto-stub":
        # The exact shape the previous fixture called valid.
        for k in pb.D7_PAYLOAD_PROTOCOL_KEYS:
            payload[k] = "<frozen by D7, never read by the gate>"
    elif break_.startswith("proto-"):
        cells = payload["cells"]
        first = cells["core-full-sarif|rust|cal-facts-small|process-cold"]
        if break_ == "proto-no-ladder":
            first.pop("repetition_ladder")
        elif break_ == "proto-ladder-incomplete":
            first["repetition_ladder"].pop("escalation_stages")
        elif break_ == "proto-no-statistic":
            first.pop("comparison_statistic")
        elif break_ == "proto-no-inconclusive":
            first.pop("inconclusive_band")
        elif break_ == "proto-no-dimension":
            first["dimensions"].pop("platform")
        elif break_ == "proto-na-without-reason":
            cells["core-full-human|python|cal-facts-small|process-cold"]["not_applicable"] = ""
        elif break_ == "proto-rollup-workload-class":
            payload["rollups"].pop("workload_class")
        elif break_ == "proto-rollup-phase":
            payload["rollups"].pop("phase")
        elif break_ == "proto-rollup-overall":
            payload["rollups"].pop("overall_g3")

    before_c1 = _git(repo, "rev-parse", "HEAD")
    nest.mkdir(parents=True, exist_ok=True)
    pay.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "C1: freeze the payload")
    c1 = _git(repo, "rev-parse", "HEAD")
    blob = _git(repo, "rev-parse", f"{c1}:{pay_rel}")

    if break_ == "no-attestation":
        return observed

    exact = pb.sha256_bytes(pay.read_bytes())
    attestation = {
        "kind": pb.D7_ATTESTATION_KIND,
        "schema": pb.D7_SCHEMA,
        "payload_path": pay_rel,
        "payload_commit_sha": c1,
        "payload_blob_sha": blob,
        "payload_sha256": exact,
        "bindings": {k: payload.get(k) for k in pb.D7_PAYLOAD_BINDING_KEYS},
        "ratification_binding": payload.get("ratification"),
    }
    if break_ == "att-kind":
        attestation["kind"] = "own.net/p022/something-else"
    elif break_ == "att-incomplete":
        attestation.pop("payload_blob_sha")
    elif break_ == "wrong-exact-hash":
        attestation["payload_sha256"] = "0" * 64
    elif break_ == "canonical-hash":
        # The old scheme's hash: canonical JSON rather than the exact bytes §6
        # names. It "identifies" the payload only up to reformatting, which is
        # the opposite of what an attestation is for.
        attestation["payload_sha256"] = pb.sha256_bytes(_canonical(payload).encode())
    elif break_ == "wrong-path":
        attestation["payload_path"] = "docs/evidence/some-other-file.json"
    elif break_ == "bad-commit":
        attestation["payload_commit_sha"] = "0" * 40
    elif break_ == "wrong-blob-sha":
        attestation["payload_blob_sha"] = "0" * 40
    elif break_ == "rebound":
        attestation["bindings"]["harness_digest"] = "e" * 64
    elif break_ == "rat-binding":
        attestation["ratification_binding"] = {"owner": "somebody else",
                                               "ratified_at": "2026-01-01T00:00:00Z",
                                               "signature": "none"}

    att.write_text(json.dumps(attestation, indent=2) + "\n", encoding="utf-8")

    if break_ == "att-uncommitted":
        return observed
    if break_ == "not-descendant":
        # A branch that forked BEFORE C1, carrying both files. The payload's
        # bytes still match the blob at C1, and C1 still exists — only the
        # attestation's commit fails to descend from it.
        payload_text = pay.read_text(encoding="utf-8")
        att_text = att.read_text(encoding="utf-8")
        _git(repo, "checkout", "-q", "-f", "-b", "sidebranch", before_c1)
        nest.mkdir(parents=True, exist_ok=True)
        pay.write_text(payload_text, encoding="utf-8")
        att.write_text(att_text, encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "C2 on a sibling branch")
        return observed

    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "C2: detached attestation")

    # #263-B does not run at C2. The repository keeps moving, and the gate has
    # to survive that or the freeze is void the moment it is used.
    _commit_file(repo, "docs/notes/after-the-freeze.md", "the work goes on\n", "post-freeze work")

    if break_ == "payload-modified-after-commit":
        # Same canonical content, different bytes, and the attestation updated to
        # match the NEW exact hash — so only git blob identity can catch it.
        pay.write_text(json.dumps(payload, indent=4) + "\n", encoding="utf-8")
        attestation["payload_sha256"] = pb.sha256_bytes(pay.read_bytes())
        att.write_text(json.dumps(attestation, indent=2) + "\n", encoding="utf-8")
    return observed


def _with_freeze(repo: Path, fn):
    saved_p, saved_a = pb.D7_PAYLOAD, pb.D7_ATTESTATION
    try:
        pb.D7_PAYLOAD = repo / "docs" / "evidence" / pb.D7_PAYLOAD.name
        pb.D7_ATTESTATION = repo / "docs" / "evidence" / pb.D7_ATTESTATION.name
        return fn()
    finally:
        pb.D7_PAYLOAD, pb.D7_ATTESTATION = saved_p, saved_a


# Each damaged freeze, and the phrase the check that owns it must produce.
# Matching the catcher is the point: without it, one broad refusal masquerades
# as twenty working checks.
_BROKEN_FREEZES = (
    # C1 shape and ratification
    ("echo", "does not declare itself a D7 payload"),
    ("payload-incomplete", "payload is incomplete, missing"),
    ("no-ratification", "no complete ratification"),
    ("signed", 'signature must be exactly "none"'),
    ("binding-mismatch", "does not describe this instrument"),
    # The instrument anchor: provenance, proved by content
    ("anchor-not-hex", "is not a full commit sha"),
    ("anchor-not-a-commit", "is not a commit in this repository"),
    ("anchor-missing-sources", "does not contain the instrument sources"),
    ("anchor-content-drift", "names a different instrument"),
    ("anchor-not-ancestor", "is not an ancestor of the payload commit"),
    # The frozen protocol: structure verified, values never read
    ("proto-stub", "cells must be a non-empty object"),
    ("proto-no-ladder", "missing: repetition_ladder"),
    ("proto-ladder-incomplete", "repetition_ladder is missing: escalation_stages"),
    ("proto-no-statistic", "missing: comparison_statistic"),
    ("proto-no-inconclusive", "missing: inconclusive_band"),
    ("proto-no-dimension", "is missing dimension(s): platform"),
    ("proto-na-without-reason", "not_applicable with no stated reason"),
    ("proto-rollup-workload-class", "missing preregistered level(s): workload_class"),
    ("proto-rollup-phase", "missing preregistered level(s): phase"),
    ("proto-rollup-overall", "missing preregistered level(s): overall_g3"),
    # C2 shape, hashes, git object identity and ancestry
    ("no-attestation", "requires a DETACHED attestation"),
    ("att-kind", "does not declare itself a D7 attestation"),
    ("att-incomplete", "attestation is incomplete, missing"),
    ("wrong-exact-hash", "exact bytes hash to"),
    ("canonical-hash", "exact bytes hash to"),
    ("wrong-path", "may not choose which file it is about"),
    ("bad-commit", "is not a commit in this repository"),
    ("wrong-blob-sha", "payload_blob_sha"),
    ("payload-modified-after-commit", "modified after it was frozen"),
    ("not-descendant", "not a descendant of the payload commit"),
    ("att-uncommitted", "not committed in this repository"),
    ("rebound", "re-binds values the payload froze differently"),
    ("rat-binding", "ratifies something other than what was frozen"),
)



def control_gate_payload_identity() -> None:
    """The gate verifies the D7 freeze §6 defines, not a lookalike.

    §6 is two GIT COMMITS: an immutable payload commit, then a detached
    attestation in a DESCENDANT commit naming that commit, that blob, and the
    sha256 of the payload's exact bytes. An earlier implementation used the same
    two letters for two sections inside one file — the word had changed
    profession — and had no equivalent of payload_blob_sha, of exact-byte
    hashing, or of the ancestry requirement at all.
    """
    _, digest = pb.load_manifest()
    problems = []
    for break_, expected in _BROKEN_FREEZES:
        with tempfile.TemporaryDirectory(prefix=f"perf-d7-{break_}-",
                                         ignore_cleanup_errors=True) as td:
            repo = Path(td) / "repo"
            try:
                _build_freeze(repo, digest, break_)
            except RuntimeError as e:
                problems.append(f"{break_}: could not build the fixture ({e})")
                continue

            def run():
                return pb.IdentityGate.load(digest)
            try:
                gate = _with_freeze(repo, run)
            except pb.InstrumentError as e:
                if expected not in str(e):
                    problems.append(f"{break_}: refused, but by the wrong check — expected "
                                    f"{expected!r}, got {str(e)[:160]!r}")
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
           f"{len(_BROKEN_FREEZES)} damaged D7 freezes, each refused by the check that owns it "
           "(payload shape, ratification, bindings, attestation shape, exact-byte hash, blob "
           "sha, path, commit, ancestry, re-binding)")


def control_gate_arms_by_data() -> None:
    """Arming is DATA, not a patch — and the harness digest does not move.

    This is the obligation that stops #263-B from being a different instrument:
    if arming changed the digest D7 froze, the freeze would be void the moment
    it was used. The freeze here is REAL — two commits in a throwaway repository
    — because a fixture the production checks cannot see is not evidence that
    the production checks pass.
    """
    workloads, digest = pb.load_manifest()
    before = pb.harness_digest()
    problems = []
    with tempfile.TemporaryDirectory(prefix="perf-d7-arm-",
                                     ignore_cleanup_errors=True) as td:
        repo = Path(td) / "repo"
        try:
            _build_freeze(repo, digest)
        except RuntimeError as e:
            fail("perf-gate-arms-by-data", f"could not build a real freeze fixture: {e}")
            return

        def run():
            gate = pb.IdentityGate.load(digest)
            return gate, pb.harness_digest()

        try:
            gate, after = _with_freeze(repo, run)
        except pb.InstrumentError as e:
            fail("perf-gate-arms-by-data", f"a VALID two-commit D7 freeze was refused: {e}")
            return

        if not gate.armed:
            problems.append("a valid freeze did not arm the gate, so #263-B could never run")
        if after != before:
            problems.append(f"arming moved the harness digest ({before[:12]} -> {after[:12]}): "
                            "the armed instrument is a different instrument")
        leaked = [k for k, v in gate.pinned.items() if "never read" in str(v)]
        if leaked:
            problems.append(f"the gate recorded frozen PROTOCOL VALUES, not just field names: "
                            f"{leaked}")
        if gate.pinned.get("protocol_fields_present") != ", ".join(
                sorted(pb.D7_PAYLOAD_PROTOCOL_KEYS)):
            problems.append("the gate did not record which protocol fields were present")
        if gate.pinned.get("attestation_commit_sha") == gate.pinned.get("payload_commit_sha"):
            problems.append("C1 and C2 were recorded as the same commit")

        # The lifecycle, asserted rather than assumed. S -> C1 -> C2 -> work,
        # and #263-B runs at the tip. The previous gate compared the accepted
        # tree against `git rev-parse HEAD`, which by this point equals none of
        # them, so a correct freeze could never have armed. If these three ever
        # collapse to one value the fixture has stopped reproducing production
        # and this control is worthless again.
        head = _git(repo, "rev-parse", "HEAD")
        anchor = gate.pinned.get(pb.D7_PAYLOAD_ANCHOR)
        c1 = gate.pinned.get("payload_commit_sha")
        c2 = gate.pinned.get("attestation_commit_sha")
        if len({head, anchor, c1, c2}) != 4:
            problems.append(f"the fixture did not exercise a moving repository: anchor="
                            f"{str(anchor)[:8]} c1={str(c1)[:8]} c2={str(c2)[:8]} "
                            f"head={head[:8]} — a gate can pass this without surviving #263-B")
        if gate.pinned.get("instrument_at_anchor_digest") != before:
            problems.append("the gate did not prove the instrument AT the anchor: it recorded "
                            f"{str(gate.pinned.get('instrument_at_anchor_digest'))[:12]} for a "
                            f"harness whose digest is {before[:12]}")
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
        ok("perf-gate-arms-by-data", "two commits in order arm the gate with no source patch, "
                                     "the harness digest is unchanged by arming, no frozen "
                                     "protocol value is recorded, and the firewall then opens")


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
    # EVERY committed calibration artifact, found structurally rather than by a
    # hardcoded path: records and exploratory sizing evidence alike must agree
    # with the rung table they describe. Naming one file meant the check went
    # blind the moment a run failed and the record was withheld — exactly when
    # the remaining evidence most needs checking.
    artifacts = []
    for cand in sorted((ROOT / "docs/evidence").glob("p022-263a-*.json")):
        try:
            doc = json.loads(cand.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(doc, dict) and "rungs" in doc and "cells" in doc:
            artifacts.append((cand, doc))
    if not artifacts:
        problems.append("no calibration artifact is committed at all, so the rung table "
                        "describes nothing that was ever measured")
    for report, rep in artifacts:
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
        h = _harness(tmp, pb.IdentityGate.load(digest))
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
        h = _harness(Path(td), pb.IdentityGate.load(digest))
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
    problems: list[str] = []
    # Pair integrity applies to EVERY committed artifact carrying a
    # reproducibility verdict, not only to reports of record. Exploratory
    # sizing evidence makes a claim about two runs too, and a claim whose
    # other half was never committed cannot be recomputed by anyone.
    for cand in sorted(Path(ROOT / "docs/evidence").glob("p022-263a-*.json")):
        try:
            doc = json.loads(cand.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        repro_any = (doc or {}).get("reproducibility")
        if not isinstance(repro_any, dict):
            continue
        e = repro_any.get("earlier_run") or {}
        if not e.get("path") or not e.get("sha256"):
            problems.append(f"{cand.name}: carries a reproducibility verdict but names no "
                            "earlier run, so the verdict rests on uncommitted data")
            continue
        mate = cand.parent / str(e["path"])
        if not mate.is_file():
            problems.append(f"{cand.name}: names earlier run {e['path']!r}, "
                            "not committed beside it")
        elif pb.sha256_bytes(mate.read_bytes()) != e["sha256"]:
            problems.append(f"{cand.name}: the committed {e['path']} does not hash to the value "
                            "its verdict was computed against")

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
                # Every axis a pair must share, checked on the shipped files.
                # The harness refuses a mismatched pair at measurement time; this
                # is the second lock, on evidence that already exists.
                mine = pb._pair_identity(rep)
                for field in pb.PAIR_IDENTITY_FIELDS:
                    a, b = earlier.get(field), mine.get(field)
                    if a != b:
                        problems.append(f"{path.name}: run A and run B disagree on {field} "
                                        f"({a!r} vs {b!r}); a pair measured under different "
                                        "source, reference, candidate or settings is not a "
                                        "reproducibility check")
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
        h = _harness(Path(td), pb.IdentityGate.load(digest))
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
