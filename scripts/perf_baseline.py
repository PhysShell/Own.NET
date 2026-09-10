#!/usr/bin/env python3
"""#263-A — the P-022 performance measurement INSTRUMENT (calibration only).

What this is, and just as importantly what it is not. This module produces the
numbers for #263's baselines; it does not decide anything with them. #263-A
freezes *how* a measurement is taken. Thresholds, the repetition count N, and
the Rust-vs-Python comparison statistic are D7's, frozen separately and before
the decisive run. Nothing here may choose them, and nothing here may be used to
choose them.

THE FIREWALL, which is the whole point of the module's shape
------------------------------------------------------------
Workloads come in two populations, declared in
``docs/evidence/p022-263a-workloads.json``:

  DECISIVE     the G3 cutover subset. These feed D7.
  CALIBRATION  generated here, deterministically, to validate the instrument.

Before the D7 freeze, a decisive workload may be enumerated, hashed, fetched,
availability-checked, and exercised by NON-TIMED structural smoke — and nothing
else. It may not be timed, its memory may not be sampled, and no engine
comparison over it may be produced *in any form, saved or not*. "We did not
write the delta down" is accounting-clean and epistemically worthless: whoever
watched the two numbers has already peeked, and every threshold they choose
afterwards is a rationalisation with a timestamp.

So the prohibition is structural rather than clerical. There is exactly one
function in this module that starts a clock, and it refuses a decisive workload
unless the identity gate is ARMED — which requires a valid D7 attestation, which
does not exist yet and cannot be forged into existence by editing this file.

TWO IDENTITY DOMAINS, deliberately not merged
---------------------------------------------
* The C1/C2 GATE domain — reference identity, harness identity, workload
  manifest identity, D7 payload validity. Dormant here. It exists now, unarmed,
  because D7's C1 will freeze the harness digest: a gate bolted on after that
  freeze makes this a different instrument and forces re-calibration and
  re-freeze. Arming it is DATA ONLY (a JSON attestation), never a source patch —
  if arming would change the harness digest, the design is wrong.
* The SESSION identity — the candidate binary's sha256, byte length and
  provenance, frozen when the session starts. The candidate is the thing under
  test, so it is emphatically NOT part of instrument identity. Drift refuses the
  remainder of the session: half the cells on binary A and half on binary B is
  not a measurement, it is two measurements wearing one hat.

Both verifications run to completion, and pass, BEFORE any clock starts, and
the notary's own cost (the digests) falls outside every measured interval. A
gate that bakes its own cost into the startup benchmark is a defect wearing a
safeguard's coat.

WHAT IS AND IS NOT SEPARATELY OBSERVABLE
----------------------------------------
Neither engine exposes per-phase timing through its production surface, and
#263-A is not authorized to add production instrumentation. So phases are
measured through a LADDER of real production invocations, each recorded as the
composed interval it actually is, with the phases it contains named. Where a
phase cannot be isolated, it is recorded as ``composed`` or ``unavailable``
rather than invented — #263 asks for unavailable stages to be marked, not
imputed. The raw per-iteration data is retained so D7 can decompose differently
if it wants to; this module never presents a derived phase as if it had been
measured directly.

Run:
  python scripts/perf_baseline.py --selftest        instrument checks, no timing
  python scripts/perf_baseline.py --calibrate       CALIBRATION_ONLY measurement
  python scripts/perf_baseline.py --smoke-decisive  non-timed structural smoke
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import random
import re
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "docs/evidence/p022-263a-workloads.json"
# D7 §6: two objects in two commits. C1 is the payload; C2 is the detached
# attestation that must live in a strictly later commit.
D7_PAYLOAD = ROOT / "docs/evidence/p022-263a-d7-payload.json"
D7_ATTESTATION = ROOT / "docs/evidence/p022-263a-d7-attestation.json"
HARNESS_VERSION = 1

CALIBRATION_ONLY = "CALIBRATION_ONLY"

# Calibration knobs, named so a control can read them.
#
# Repetitions is the sanctioned sizing knob: an owner-bounded escalation may
# raise it for a report of record. WARMUP IS NOT. It was changed from 2 to 3
# alongside a repetitions escalation that had been authorised on its own, which
# turned one permitted knob into two turned after seeing which runs went red.
# A committed calibration must use this default; changing it is a deliberate
# policy edit in one place, not a flag someone passes.
DEFAULT_CALIBRATION_REPETITIONS = 5
DEFAULT_WARMUP_DISCARDS = 2


class InstrumentError(RuntimeError):
    """The instrument refuses to proceed. Always fail-closed, never a warning."""


class FirewallBreach(InstrumentError):
    """An attempt to measure a decisive workload before the D7 freeze."""


# --- digests ---------------------------------------------------------------


def sha256_file(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_CRLF = b"\r\n"
_LF = b"\n"


def normalized_text(data: bytes) -> bytes:
    """Line endings normalized, so identity is content and not checkout policy.

    One function, because every identity D7 freezes has to agree about what the
    same content means. Round 3 fixed the harness digest and left
    ``load_manifest`` hashing raw bytes two hundred lines away, which is the
    same defect with a different variable name.
    """
    return data.replace(_CRLF, _LF)


def sha256_text_file(path: Path) -> tuple[str, int]:
    """Hash a TEXT file by its content, with line endings normalized.

    The harness digest must name the INSTRUMENT, not the checkout it came from.
    A Windows checkout with ``core.autocrlf=true`` stores the same source with
    CRLF, so a raw-byte digest gives one instrument two identities — and D7's C1
    freezes that value, so a freeze would arm on one platform and refuse on the
    other while #263-B has to run on both. Caught by CI: the same tree hashed
    af32f04ddbad on Linux and 51ef2ca2422a on Windows.

    This repository already knows the defect class — ``.gitattributes`` pins
    ``docs/evidence/*.json`` to LF because campaign definition hashes hit it
    first — but an attribute only governs files git checks out under it. A file
    already in a working tree, a zip download, or a contributor whose clone
    predates the rule all still differ. An identity that D7 will freeze should
    depend on content, so it is normalized here rather than delegated to a
    checkout setting.

    Raw ``sha256_file`` stays raw: the candidate binary is bytes, and
    normalizing a binary would be a different kind of wrong.
    """
    data = normalized_text(path.read_bytes())
    return sha256_bytes(data), len(data)


SELF = Path(__file__).resolve()

# The files whose CONTENT is the instrument. The manifest is in here on
# purpose: it means proving the harness digest at a commit also proves the
# workload manifest at that commit, so there is no second anchor check to write
# and no second anchor check to get wrong.
INSTRUMENT_SOURCES: tuple[Path, ...] = (SELF, MANIFEST)


def _instrument_rel(path: Path) -> str:
    """Repository-relative path, so the same source can be read out of any
    checkout of this repository rather than only out of this one."""
    return path.relative_to(ROOT).as_posix()


def _harness_digest_from(parts: Sequence[tuple[str, bytes]]) -> str:
    """The digest formula, written ONCE.

    ``harness_digest`` reads the working tree and ``harness_digest_at`` reads
    git blobs at a commit. The D7 anchor proof compares one against the other,
    so if these were two implementations of "the same" formula the proof would
    be comparing two functions and calling their agreement meaningful.
    """
    lines = [f"{name}:{sha256_bytes(normalized_text(data))}" for name, data in parts]
    return sha256_bytes("\n".join(lines).encode("utf-8"))


def harness_digest() -> str:
    """The instrument's own identity: this file plus the frozen manifest.

    D7's C1 freezes this value. It deliberately does NOT include the candidate
    binary or any attestation: the candidate is the thing under test, and an
    attestation that changed the digest it attests to could never be written
    down.
    """
    return _harness_digest_from([(p.name, p.read_bytes()) for p in INSTRUMENT_SOURCES])


def harness_digest_at(repo: Path, commit: str) -> str | None:
    """The same identity, computed from the instrument as it existed AT a commit.

    This is what makes the D7 anchor a provenance claim rather than a position
    assertion: C1 names the accepted #263-A commit S, and the gate proves that
    the instrument at S really is the instrument whose digest C1 froze. ``None``
    means S does not contain the instrument at all, which is a refusal, not a
    pass.
    """
    parts: list[tuple[str, bytes]] = []
    for src in INSTRUMENT_SOURCES:
        rc, data = _git_bytes(repo, "show", f"{commit}:{_instrument_rel(src)}")
        if rc != 0:
            return None
        parts.append((src.name, data))
    return _harness_digest_from(parts)


# --- identity: the D7 C1/C2 gate (dormant) ---------------------------------


# D7 §6 defines TWO GIT COMMITS, not two sections of one file.
#
#   C1  the immutable payload commit — thresholds/rules/rollups, the Python
#       reference sha, the #263-A tree sha, harness digest and version, the
#       workload manifest digest, and the owner's ratification.
#   C2  a detached attestation in a DESCENDANT commit — the payload's commit
#       sha, its blob sha, the sha256 of its EXACT bytes, the instrument /
#       reference / workload bindings, and the ratification binding.
#
# The previous implementation used the same two letters for something else: C1
# and C2 were sections INSIDE one payload, with "c2" holding threshold values.
# The word had quietly changed profession, and an equivalent-looking scheme is
# not the frozen scheme. What follows implements §6 as quoted, including the
# parts the old design had no equivalent of at all: payload_blob_sha, the
# exact-byte hash rather than a canonical-JSON one, and proof that C2's commit
# is a descendant of C1's.
D7_PAYLOAD_KIND = "own.net/p022/d7-payload"          # C1
D7_ATTESTATION_KIND = "own.net/p022/d7-attestation"  # C2

D7_SCHEMA = 1

# C1 content.
#
# The gate must never READ a threshold: a #263-A artifact that quoted one would
# leak the number this module exists to keep out. It does not follow that the
# gate may ignore whether a preregistration is THERE. The previous version
# checked three key names for presence, and its own fixture armed the gate with
#
#     thresholds = "<frozen by D7, never read by the gate>"
#     rules      = "<frozen by D7, never read by the gate>"
#     rollups    = "<frozen by D7, never read by the gate>"
#
# — two immaculate git commits, three celebratory strings, and the decisive
# firewall opens. Structure is verified; values are never read, compared,
# ordered or echoed.
D7_PAYLOAD_PROTOCOL_KEYS = ("cells", "rollups")

# Per D7: every (phase x workload-id x platform x regime) cell carries a
# budget/regression bound, a pass/fail rule, an inconclusive band, a repetition
# ladder with its stopping rule, a comparison statistic, and RSS/allocation
# treatment — or says in so many words that it does not apply.
D7_CELL_DIMENSIONS = ("phase", "workload_id", "platform", "regime")
D7_CELL_RULE_KEYS = ("bound", "pass_fail_rule", "inconclusive_band", "repetition_ladder",
                     "comparison_statistic", "rss_policy", "allocation_policy")
D7_LADDER_KEYS = ("initial_n", "escalation_stages", "transition_predicates", "max_n",
                  "terminal_outcome")
D7_CELL_NA_KEY = "not_applicable"

# Preregistered roll-ups, cell -> phase -> overall.
D7_ROLLUP_LEVELS = ("workload_class", "phase", "overall_g3")

# The accepted #263-A source commit S. DECLARED by C1 and PROVED by content —
# it is deliberately not in D7_PAYLOAD_BINDING_KEYS, because those are compared
# against what this process observes and S is precisely the thing that must NOT
# equal the current position.
D7_PAYLOAD_ANCHOR = "instrument_anchor_commit"

D7_PAYLOAD_BINDING_KEYS = (
    "python_reference_commit", "python_reference_tree",
    "harness_digest", "harness_version", "workload_manifest_sha256",
)
D7_PAYLOAD_KEYS = ("kind", "schema", *D7_PAYLOAD_PROTOCOL_KEYS, D7_PAYLOAD_ANCHOR,
                   *D7_PAYLOAD_BINDING_KEYS, "ratification")
D7_RATIFICATION_KEYS = ("owner", "ratified_at", "signature")

# C2 content.
D7_ATTESTATION_KEYS = ("kind", "schema", "payload_path", "payload_commit_sha",
                       "payload_blob_sha", "payload_sha256", "bindings",
                       "ratification_binding")

_HEX40 = re.compile(r"\A[0-9a-f]{40}\Z")


def _present(value: object) -> bool:
    """Is this field THERE — without asking what it says.

    A blank string, an empty list and an empty object are all structurally
    absent however confidently they are typed. Nothing here compares, orders or
    records a value, so a threshold cannot leak through this function.
    """
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, tuple, dict)):
        return len(value) > 0
    return value is not None


def _d7_protocol_problems(payload: dict[str, object]) -> list[str]:
    """Does C1 carry a preregistration D7 would recognise?

    Every problem names the field it is about, so a control can match a damaged
    freeze against the check that owns it. One broad "malformed protocol"
    refusal would let a dozen missing checks hide behind a single passing case.
    """
    problems: list[str] = []

    cells = payload.get("cells")
    if not isinstance(cells, dict) or not cells:
        problems.append(
            "cells must be a non-empty object keyed by cell id, one entry per "
            "(" + " x ".join(D7_CELL_DIMENSIONS) + ")")
    else:
        for cid, spec in sorted(cells.items(), key=lambda kv: str(kv[0])):
            where = f"cell {str(cid)!r}"
            if not isinstance(spec, dict):
                problems.append(f"{where} is not an object")
                continue

            dims = spec.get("dimensions")
            if not isinstance(dims, dict):
                problems.append(f"{where} declares no dimensions object")
            else:
                absent = [d for d in D7_CELL_DIMENSIONS if not _present(dims.get(d))]
                if absent:
                    problems.append(f"{where} is missing dimension(s): " + ", ".join(absent))

            if D7_CELL_NA_KEY in spec:
                # An explicit N/A is a preregistered decision and needs a stated
                # reason. A bare `not_applicable: true` is a way of writing
                # "no rule" that reads like a rule.
                if not _present(spec.get(D7_CELL_NA_KEY)):
                    problems.append(f"{where} is marked {D7_CELL_NA_KEY} with no stated reason")
                continue

            absent = [k for k in D7_CELL_RULE_KEYS if not _present(spec.get(k))]
            if absent:
                problems.append(
                    f"{where} carries neither a complete rule nor an explicit "
                    f"{D7_CELL_NA_KEY} — missing: " + ", ".join(absent))

            ladder = spec.get("repetition_ladder")
            if _present(ladder):
                if not isinstance(ladder, dict):
                    problems.append(f"{where} repetition_ladder is not an object")
                else:
                    gaps = [k for k in D7_LADDER_KEYS if not _present(ladder.get(k))]
                    if gaps:
                        problems.append(
                            f"{where} repetition_ladder is missing: " + ", ".join(gaps))

    rollups = payload.get("rollups")
    if not isinstance(rollups, dict):
        problems.append("rollups must be an object carrying the preregistered levels "
                        + ", ".join(D7_ROLLUP_LEVELS))
    else:
        absent = [lv for lv in D7_ROLLUP_LEVELS if not _present(rollups.get(lv))]
        if absent:
            problems.append("rollups is missing preregistered level(s): " + ", ".join(absent))
    return problems
_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")


def _git_in(repo: Path, *args: str) -> tuple[int, str]:
    """Run git inside a named repository. Always outside a measured interval.

    Counted by the notary control: obligation (c) is that identity work never
    bills the benchmark for its own cost, and the only way to know that is to
    count the calls while a clock is running.
    """
    r = subprocess.run(["git", *args], capture_output=True, cwd=str(repo), check=False)
    return r.returncode, r.stdout.decode("utf-8", "replace").strip()


def _git_bytes(repo: Path, *args: str) -> tuple[int, bytes]:
    """Like ``_git_in`` but returns RAW stdout.

    ``git show <commit>:<path>`` produces file content, and content must not be
    decoded-and-stripped on its way to a hash: stripping a trailing newline
    would make a file hash differently depending on which reader found it.
    """
    r = subprocess.run(["git", *args], capture_output=True, cwd=str(repo), check=False)
    return r.returncode, r.stdout


def _committed_blob_matches(repo: Path, rev: str, path_in_repo: str,
                            on_disk: Path) -> tuple[bool, str]:
    """Is this file, as git sees it, the blob committed at ``rev``:``path``?

    ``git hash-object`` applies the same filters git would, so a CRLF checkout
    on Windows compares equal to an LF blob instead of reading as tampering.
    """
    rc, committed = _git_in(repo, "rev-parse", "--verify", "--quiet", f"{rev}:{path_in_repo}")
    if rc != 0 or not committed:
        return False, f"nothing is committed at {path_in_repo!r} in {rev[:12]}"
    rc, ondisk = _git_in(repo, "hash-object", "--", str(on_disk))
    if rc != 0 or not ondisk:
        return False, f"git could not hash {on_disk.name} on disk"
    if ondisk != committed:
        return False, (f"{on_disk.name} on disk ({ondisk[:12]}) is not the blob committed at "
                       f"{rev[:12]} ({committed[:12]}): it was modified after it was frozen")
    return True, committed


@dataclass(frozen=True)
class IdentityGate:
    """The D7 C1/C2 domain. Present, verified, and — until D7 — unarmed.

    Armed state requires BOTH commits of §6 and every check in ``load``. There
    is no flag, no environment variable and no code path that arms it otherwise,
    because a gate that can be waved through is a comment.

    What arming costs: an immutable payload commit carrying the frozen protocol
    and every binding; then, in a strictly LATER commit, a detached attestation
    naming that commit, that blob, and the sha256 of the payload's exact bytes.
    Two commits in order, both reviewable, neither able to be written after the
    fact without leaving the other inconsistent.

    What this does NOT prove: git object identity is not a signature. Anyone
    with write access could author both commits. The ratification records who
    and when, and records plainly when it is unsigned.

    Arming stays DATA-ONLY — two JSON files and two commits — so the harness
    digest D7 freezes does not move when the gate arms.
    """

    armed: bool
    reason: str
    pinned: dict[str, str] = field(default_factory=dict)
    observed: dict[str, str] = field(default_factory=dict)

    @staticmethod
    def observe(manifest_digest: str, root: Path = ROOT) -> dict[str, str]:
        """What this process can see about itself, for C1 to be checked against.

        These are the values C1 must EQUAL, so every one of them has to be
        stable across the freeze that writes C1 and C2. ``instrument_tree_sha =
        git rev-parse HEAD`` used to be in here and was none of those things:
        the real lifecycle is

            S (accepted #263-A tree) -> C1 -> C2 -> #263-B runs

        so by the time #263-B runs, HEAD is at least C2 and can never equal S.
        A freeze that satisfied this check would have to name a future
        content-addressed commit sha inside the commit that determines it, and
        git is not moved by human ingenuity. The instrument anchor is now
        DECLARED by C1 and proved by content — see ``harness_digest_at`` — and
        the current position is not asserted at all.
        """
        return {
            "python_reference_commit": python_reference_commit(root),
            "python_reference_tree": python_reference_tree(root),
            "harness_digest": harness_digest(),
            "harness_version": str(HARNESS_VERSION),
            "workload_manifest_sha256": manifest_digest,
        }

    @staticmethod
    def requirements() -> list[str]:
        """What a D7 freeze must satisfy, recorded in the report so the evidence
        describes its own gate instead of asking a reader to trust this file."""
        return [
            f"C1: a payload at {D7_PAYLOAD.name} declaring kind={D7_PAYLOAD_KIND!r}, carrying "
            + ", ".join(D7_PAYLOAD_KEYS),
            "C1 carries a STRUCTURALLY COMPLETE preregistration: " + ", ".join(
                D7_PAYLOAD_PROTOCOL_KEYS) + "; each cell declares "
            + ", ".join(D7_CELL_DIMENSIONS) + " and either " + ", ".join(D7_CELL_RULE_KEYS)
            + " (the ladder carrying " + ", ".join(D7_LADDER_KEYS) + ") or an explicit "
            + D7_CELL_NA_KEY + " with a reason; roll-ups carry "
            + ", ".join(D7_ROLLUP_LEVELS) + ". Values are never read",
            f"C1 declares {D7_PAYLOAD_ANCHOR} S, and the instrument AT S hashes to the "
            "harness_digest C1 froze; S is an ancestor of C1. The CURRENT position is never "
            "required to equal S, because by #263-B it cannot be",
            "C1's bindings equal what this process observes: "
            + ", ".join(D7_PAYLOAD_BINDING_KEYS),
            f"C2: a detached attestation at {D7_ATTESTATION.name} declaring "
            f"kind={D7_ATTESTATION_KIND!r}, carrying " + ", ".join(D7_ATTESTATION_KEYS),
            "C2's payload_sha256 equals the sha256 of the payload's EXACT BYTES",
            "C2's payload_blob_sha equals the git blob sha of the payload at payload_commit_sha, "
            "and the payload's working-tree bytes are that blob",
            "C2's own commit is a strict DESCENDANT of payload_commit_sha",
            "C2's bindings and ratification_binding equal C1's",
            "both objects are committed and unmodified in the working tree",
        ]

    @staticmethod
    def load(manifest_digest: str, reference_sha: str | None = None) -> IdentityGate:
        # Observe the repository the freeze actually lives in. When those are
        # two different repositories the gate would verify one and describe the
        # other, which is how the fixtures used to pass while production could
        # never have armed.
        freeze_root = _repo_root(D7_PAYLOAD)
        root = freeze_root or ROOT
        observed = IdentityGate.observe(manifest_digest, root)
        if not D7_PAYLOAD.is_file():
            return IdentityGate(
                armed=False,
                reason="no D7 payload on disk: the freeze has not happened, so the gate is "
                       "dormant by design and every decisive measurement is refused",
                observed=observed)

        raw_payload = D7_PAYLOAD.read_bytes()
        payload = _read_json_or_refuse(D7_PAYLOAD, "D7 payload")

        # --- C1 shape -----------------------------------------------------
        if payload.get("kind") != D7_PAYLOAD_KIND or payload.get("schema") != D7_SCHEMA:
            raise InstrumentError(
                f"{D7_PAYLOAD.name} does not declare itself a D7 payload "
                f"(kind={payload.get('kind')!r}, schema={payload.get('schema')!r}). Matching "
                "identity values are not a freeze: they are values anyone with this repository "
                "can compute.")
        missing = [k for k in D7_PAYLOAD_KEYS if k not in payload]
        if missing:
            raise InstrumentError("the D7 payload is incomplete, missing: " + ", ".join(missing))
        rat = payload["ratification"]
        if not isinstance(rat, dict) or [k for k in D7_RATIFICATION_KEYS if k not in rat]:
            raise InstrumentError(
                "the D7 payload carries no complete ratification (needs "
                + ", ".join(D7_RATIFICATION_KEYS) + "): an unratified freeze is a draft")
        if rat["signature"] != "none":
            raise InstrumentError(
                'ratification.signature must be exactly "none" for this version of the '
                "instrument. Signed ratification is not part of the accepted contract: it would "
                "need a real signing key and a control exercising ACCEPTANCE, neither of which "
                "exists here, and a signature check nothing can test is not a check.")

        # --- C1 bindings against observation ------------------------------
        mismatched = [k for k in D7_PAYLOAD_BINDING_KEYS if str(payload[k]) != observed[k]]
        if mismatched:
            raise InstrumentError(
                "the D7 payload does not describe this instrument/reference/workload: "
                + "; ".join(f"{k} pinned {str(payload[k])[:12]!r} but observed "
                            f"{observed[k][:12]!r}" for k in mismatched))

        # --- C2 shape -----------------------------------------------------
        if not D7_ATTESTATION.is_file():
            raise InstrumentError(
                f"a D7 payload is present but {D7_ATTESTATION.name} is not. §6 requires a "
                "DETACHED attestation in a descendant commit; a payload alone is a draft.")
        att = _read_json_or_refuse(D7_ATTESTATION, "D7 attestation")
        if att.get("kind") != D7_ATTESTATION_KIND or att.get("schema") != D7_SCHEMA:
            raise InstrumentError(
                f"{D7_ATTESTATION.name} does not declare itself a D7 attestation "
                f"(kind={att.get('kind')!r}, schema={att.get('schema')!r})")
        missing = [k for k in D7_ATTESTATION_KEYS if k not in att]
        if missing:
            raise InstrumentError(
                "the D7 attestation is incomplete, missing: " + ", ".join(missing))

        # --- exact-byte hash ----------------------------------------------
        # §6 says sha256 of the EXACT payload bytes. Not a canonical-JSON
        # re-serialisation: that would let two different files claim one hash,
        # which is the opposite of what an attestation is for.
        exact = sha256_bytes(raw_payload)
        declared = str(att["payload_sha256"])
        if not _HEX64.match(declared):
            raise InstrumentError(f"payload_sha256 is not a sha256: {declared[:24]!r}")
        if declared != exact:
            raise InstrumentError(
                f"the D7 attestation attests payload_sha256 {declared[:12]} but the payload's "
                f"exact bytes hash to {exact[:12]}")

        # --- the frozen protocol: structure verified, values never read ----
        shape = _d7_protocol_problems(payload)
        if shape:
            raise InstrumentError(
                "the D7 payload does not carry a preregistration §6 would recognise: "
                + "; ".join(shape) + ". The gate never reads a threshold VALUE, but a "
                "freeze whose protocol is structurally empty is not a freeze.")

        # --- git identity: repo, blob, commit, ancestry --------------------
        if freeze_root is None:
            raise InstrumentError(
                "the D7 freeze names commits but is not inside a git repository, so its object "
                "identity cannot be verified. Fail-closed: unverifiable is not verified.")
        canonical = _repo_relative(root, D7_PAYLOAD)
        att_rel = _repo_relative(root, D7_ATTESTATION)
        if canonical is None or att_rel is None:
            raise InstrumentError("the D7 objects are not inside the repository containing them")
        if str(att["payload_path"]) != canonical:
            raise InstrumentError(
                f"the attestation attests {str(att['payload_path'])!r}, but this instrument reads "
                f"its payload from {canonical!r}: an attestation may not choose which file it is "
                "about")

        c1 = str(att["payload_commit_sha"])
        if not _HEX40.match(c1):
            raise InstrumentError(f"payload_commit_sha is not a full commit sha: {c1[:24]!r}")
        rc, _ = _git_in(root, "rev-parse", "--verify", "--quiet", f"{c1}^{{commit}}")
        if rc != 0:
            raise InstrumentError(
                f"payload_commit_sha {c1[:12]} is not a commit in this repository")

        # --- the instrument anchor: provenance, not current position -------
        #
        # C1 declares S, the accepted #263-A source commit. The gate proves S
        # rather than comparing it to wherever the repository is standing:
        #
        #   S exists, and contains the instrument
        #   the instrument AT S hashes to the harness_digest C1 froze
        #   S is an ancestor of C1
        #
        # and the rest of the chain is already proved below: C1 is a strict
        # ancestor of C2, and C2 is found by `git log` in HEAD's history. So
        # S <= C1 < C2 <= HEAD without ever requiring HEAD to equal anything.
        anchor = str(payload[D7_PAYLOAD_ANCHOR])
        if not _HEX40.match(anchor):
            raise InstrumentError(
                f"{D7_PAYLOAD_ANCHOR} is not a full commit sha: {anchor[:24]!r}")
        rc, _ = _git_in(root, "rev-parse", "--verify", "--quiet", f"{anchor}^{{commit}}")
        if rc != 0:
            raise InstrumentError(
                f"{D7_PAYLOAD_ANCHOR} {anchor[:12]} is not a commit in this repository")
        digest_at_anchor = harness_digest_at(root, anchor)
        if digest_at_anchor is None:
            raise InstrumentError(
                f"{D7_PAYLOAD_ANCHOR} {anchor[:12]} does not contain the instrument sources ("
                + ", ".join(_instrument_rel(src) for src in INSTRUMENT_SOURCES)
                + "): it cannot be the accepted #263-A commit")
        if digest_at_anchor != str(payload["harness_digest"]):
            raise InstrumentError(
                f"the instrument at {D7_PAYLOAD_ANCHOR} {anchor[:12]} hashes to "
                f"{digest_at_anchor[:12]}, but C1 froze harness_digest "
                f"{str(payload['harness_digest'])[:12]}: the anchor names a different "
                "instrument than the one the freeze describes")
        rc, _ = _git_in(root, "merge-base", "--is-ancestor", anchor, c1)
        if rc != 0:
            raise InstrumentError(
                f"{D7_PAYLOAD_ANCHOR} {anchor[:12]} is not an ancestor of the payload commit "
                f"{c1[:12]}: a freeze cannot precede the instrument it freezes")

        rc, blob_at_c1 = _git_in(root, "rev-parse", "--verify", "--quiet", f"{c1}:{canonical}")
        if rc != 0 or not blob_at_c1:
            raise InstrumentError(f"the D7 payload is not committed at {canonical!r} in {c1[:12]}")
        if str(att["payload_blob_sha"]) != blob_at_c1:
            raise InstrumentError(
                f"the attestation attests payload_blob_sha {str(att['payload_blob_sha'])[:12]} "
                f"but the payload's blob at {c1[:12]} is {blob_at_c1[:12]}")
        rc, ondisk = _git_in(root, "hash-object", "--", str(D7_PAYLOAD))
        if rc != 0 or ondisk != blob_at_c1:
            raise InstrumentError(
                f"the D7 payload on disk ({ondisk[:12]}) is not the blob committed at "
                f"{c1[:12]} ({blob_at_c1[:12]}): it was modified after it was frozen")

        # C2 must live in a STRICTLY LATER commit. Same-commit is not a
        # detached attestation, it is a footnote.
        rc, c2 = _git_in(root, "log", "-1", "--format=%H", "--", att_rel)
        if rc != 0 or not _HEX40.match(c2):
            raise InstrumentError(
                f"{D7_ATTESTATION.name} is not committed in this repository: an uncommitted "
                "attestation is a local edit, not an owner's act")
        if c2 == c1:
            # DEFENSIVE AND UNCONSTRUCTIBLE. §6 requires a descendant commit,
            # and a same-commit state cannot be built with ordinary git: the
            # attestation would have to contain the sha of the commit that
            # contains the attestation, and git shas are content-addressed. The
            # guard stays because "cannot currently be built" is not "cannot
            # exist" — a hand-crafted object or a future tool could present one.
            # It is untested for that reason, and said so rather than faked with
            # a mocked git.
            raise InstrumentError(
                f"the D7 attestation is in the SAME commit as the payload ({c1[:12]}). §6 "
                "requires a descendant commit: an attestation written in the act it attests to "
                "proves only that both were typed at once.")
        rc, _ = _git_in(root, "merge-base", "--is-ancestor", c1, c2)
        if rc != 0:
            raise InstrumentError(
                f"the D7 attestation's commit {c2[:12]} is not a descendant of the payload "
                f"commit {c1[:12]}: it attests a history it is not in")
        good, detail = _committed_blob_matches(root, c2, att_rel, D7_ATTESTATION)
        if not good:
            raise InstrumentError(f"the D7 attestation is not its committed blob: {detail}")

        # --- C2 bindings and ratification binding --------------------------
        bindings = att["bindings"]
        if not isinstance(bindings, dict):
            raise InstrumentError("the D7 attestation's bindings are not an object")
        rebound = [k for k in D7_PAYLOAD_BINDING_KEYS
                   if str(bindings.get(k, "")) != str(payload[k])]
        if rebound:
            raise InstrumentError(
                "the D7 attestation re-binds values the payload froze differently: "
                + ", ".join(rebound))
        if att["ratification_binding"] != payload["ratification"]:
            raise InstrumentError(
                "the D7 attestation's ratification_binding does not equal the payload's "
                "ratification: the attestation ratifies something other than what was frozen")

        _cells = payload["cells"]
        _cell_count = len(_cells) if isinstance(_cells, dict) else 0
        pinned = {
            **{k: str(payload[k]) for k in D7_PAYLOAD_BINDING_KEYS},
            "payload_commit_sha": c1,
            "payload_blob_sha": blob_at_c1,
            "payload_sha256": exact,
            "attestation_commit_sha": c2,
            "ratified_by": str(rat["owner"]),
            "ratified_at": str(rat["ratified_at"]),
            "signature": "unsigned (declared): two committed objects, which anyone with "
                         "repository write access could author",
            D7_PAYLOAD_ANCHOR: anchor,
            "instrument_at_anchor_digest": digest_at_anchor,
            # SHAPE, never values: a #263-A artifact must not carry a threshold.
            # Counts describe how much preregistration was found; they say
            # nothing about what any of it says.
            "protocol_fields_present": ", ".join(sorted(D7_PAYLOAD_PROTOCOL_KEYS)),
            "protocol_cells_specified": str(_cell_count),
            "protocol_rollup_levels": ", ".join(D7_ROLLUP_LEVELS),
        }
        return IdentityGate(
            armed=True,
            reason=(f"D7 freeze verified: C1 payload at {c1[:12]}, C2 attestation at "
                    f"{c2[:12]} (descendant), exact-byte sha256 {exact[:12]}"),
            pinned=pinned, observed=observed)


def _read_json_or_refuse(path: Path, what: str) -> dict[str, object]:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:  # fail closed, never open
        raise InstrumentError(f"a {what} exists but cannot be read: {e}") from e
    if not isinstance(obj, dict):
        raise InstrumentError(f"the {what} is not a JSON object")
    return obj


def _repo_root(inside: Path) -> Path | None:
    """The Git TREE ROOT, asked of git rather than guessed from a parent directory.

    This is load-bearing and was got wrong once. ``<rev>:<path>`` resolves the
    path from the root of the tree; only a path starting ``./`` or ``../`` is
    read relative to the current directory. Treating the file's own directory as
    the repository therefore produced ``<rev>:p022-...json`` for a file that
    actually lives at ``docs/evidence/p022-...json`` — a lookup that fails for
    every real layout, so no production freeze could ever have armed. The
    throwaway fixtures put both objects at the root of their repository, where
    the wrong model happens to be right, so every control agreed.
    """
    rc, out = _git_in(inside if inside.is_dir() else inside.parent,
                      "rev-parse", "--show-toplevel")
    if rc != 0 or not out:
        return None
    return Path(out)


def _repo_relative(repo: Path, path: Path) -> str | None:
    """Path as git names it: relative to the TREE ROOT, forward slashes.

    None when the file is outside the repository — a case that must refuse
    rather than silently degrade to a basename.
    """
    try:
        return path.resolve().relative_to(Path(repo).resolve()).as_posix()
    except ValueError:
        return None


@dataclass
class SessionIdentity:
    """The candidate under test, frozen when the session starts.

    Separate from the gate on purpose: the candidate is the SUBJECT of the
    measurement, not part of the instrument. Its drift does not mean the
    instrument changed, it means the session is measuring two different things
    and must stop.
    """

    path: str
    sha256: str
    bytes_len: int
    frozen_at: str
    measurements_taken: int = 0

    @staticmethod
    def freeze(candidate: Path) -> SessionIdentity:
        digest, n = sha256_file(candidate)
        return SessionIdentity(path=str(candidate), sha256=digest, bytes_len=n,
                               frozen_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def reverify(self) -> None:
        """Re-read the candidate. Called between cells, never inside an interval."""
        digest, n = sha256_file(Path(self.path))
        if digest != self.sha256 or n != self.bytes_len:
            raise InstrumentError(
                f"the candidate binary changed during the session (was {self.sha256[:12]}, "
                f"{self.bytes_len} bytes; now {digest[:12]}, {n} bytes) after "
                f"{self.measurements_taken} measurement(s). The rest of this session is refused: "
                "cells measured on two different binaries are not one measurement.")


# --- environment -----------------------------------------------------------


def _cpu_model() -> str:
    if sys.platform.startswith("linux"):
        try:
            for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
        except OSError:
            pass
    return platform.processor() or platform.machine()


def _total_ram_bytes() -> int | None:
    if sys.platform.startswith("linux"):
        try:
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
        except (OSError, ValueError):
            return None
    if os.name == "nt":
        class _MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        ms = _MS()
        ms.dwLength = ctypes.sizeof(_MS)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):  # type: ignore[attr-defined]
            return int(ms.ullTotalPhys)
    return None


def _tool_version(argv: list[str]) -> str:
    try:
        r = subprocess.run(argv, capture_output=True, check=False, timeout=60)
        return (r.stdout or r.stderr).decode("utf-8", "replace").strip().splitlines()[0][:120]
    except (OSError, subprocess.SubprocessError, IndexError):
        return ""


def environment_fingerprint() -> dict[str, object]:
    """§4. Recorded, not assumed — a baseline whose machine is unknown is a number."""
    return {
        "platform": sys.platform,
        "os": platform.platform(),
        "cpu_model": _cpu_model(),
        "cpu_count": os.cpu_count(),
        "ram_bytes": _total_ram_bytes(),
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "dotnet_sdk": _tool_version(["dotnet", "--version"]),
        "rustc": _tool_version(["rustc", "--version"]),
        "runner_class": os.environ.get("RUNNER_NAME") or os.environ.get("HOSTNAME") or "local",
        "ci": bool(os.environ.get("CI")),
    }


# --- peak RSS, by a NAMED tool (§8) ----------------------------------------


class RssProbe:
    """Peak resident set of a child process, captured by a NAMED mechanism.

    POSIX: ``os.wait4`` — the kernel's own per-child accounting, ``ru_maxrss``
    for exactly the process we spawned. Chosen over ``/usr/bin/time -v`` as the
    primary because GNU time is a package that may simply be absent (it is
    absent on the container this was first calibrated on), and "the tool was
    missing" is not a memory measurement. ``/usr/bin/time -v`` remains as the
    documented fallback where wait4 is unavailable.

    Windows: a Job Object, read through ``QueryInformationJobObject`` for
    ``PeakProcessMemoryUsed``.

    Anywhere else: None WITH A REASON, so a silent absence can never be read as
    a measured zero.
    """

    def __init__(self) -> None:
        self.reason = ""
        if hasattr(os, "wait4"):
            self.mechanism = "posix os.wait4 (ru_maxrss)"
        elif os.name == "nt":
            self.mechanism = "win32 job object (PeakProcessMemoryUsed)"
        elif Path("/usr/bin/time").is_file():
            self.mechanism = "/usr/bin/time -v"
        else:
            self.mechanism = "none"
            self.reason = f"no named RSS mechanism on {sys.platform}"

    # ru_maxrss is kilobytes on Linux and bytes on macOS/BSD. Recorded, because
    # a memory number whose unit was guessed is worse than none.
    @property
    def maxrss_unit_bytes(self) -> int:
        return 1 if sys.platform == "darwin" else 1024

    def wrap(self, argv: list[str], tmp: Path) -> tuple[list[str], Path | None]:
        if self.mechanism.startswith("/usr/bin/time"):
            out = tmp / f"rss-{os.getpid()}-{time.monotonic_ns()}.txt"
            return ["/usr/bin/time", "-v", "-o", str(out), *argv], out
        return argv, None

    def read(self, sidecar: Path | None) -> int | None:
        if sidecar is None or not sidecar.is_file():
            return None
        for line in sidecar.read_text(encoding="utf-8", errors="replace").splitlines():
            if "Maximum resident set size" in line:
                try:
                    return int(line.rsplit(":", 1)[1].strip()) * 1024
                except (ValueError, IndexError):
                    return None
        return None

    def read_windows_peak(self, job: object | None) -> tuple[int | None, str]:
        if os.name != "nt" or job is None:
            return None, ""
        class _IO(ctypes.Structure):
            _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                        ("WriteOperationCount", ctypes.c_ulonglong),
                        ("OtherOperationCount", ctypes.c_ulonglong),
                        ("ReadTransferCount", ctypes.c_ulonglong),
                        ("WriteTransferCount", ctypes.c_ulonglong),
                        ("OtherTransferCount", ctypes.c_ulonglong)]
        class _EXT(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", ctypes.c_byte * 48),
                        ("IoInfo", _IO),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]
        info = _EXT()
        ok = ctypes.windll.kernel32.QueryInformationJobObject(  # type: ignore[attr-defined]
            job, 9, ctypes.byref(info), ctypes.sizeof(_EXT), None)
        if not ok:
            return None, "QueryInformationJobObject failed"
        peak = int(info.PeakProcessMemoryUsed)
        if peak == 0:
            # Not a measured zero. A process that exits before the job
            # assignment lands is never accounted, and reporting 0 bytes for it
            # would be the most confident possible lie.
            return None, "the child exited before job assignment; peak not accounted"
        return peak, ""


# --- workloads -------------------------------------------------------------


@dataclass(frozen=True)
class Workload:
    id: str
    population: str
    kind: str
    spec: dict[str, object]

    @property
    def decisive(self) -> bool:
        return self.population == "decisive"


def load_manifest() -> tuple[list[Workload], str]:
    raw = MANIFEST.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    out: list[Workload] = []
    for population in ("decisive", "calibration"):
        for item in data[population]:
            out.append(Workload(id=str(item["id"]), population=population,
                                kind=str(item["kind"]), spec=dict(item)))
    ids = [w.id for w in out]
    if len(set(ids)) != len(ids):
        raise InstrumentError(f"the workload manifest has duplicate ids: {ids}")
    # Normalized, like every other identity D7 freezes. `.gitattributes` pins
    # this file to LF, but an attribute only governs files git checks out under
    # it: a zip download or a clone predating the rule still differs, and C1
    # freezes this value.
    return out, sha256_bytes(normalized_text(raw))


def materialize_calibration(w: Workload, tmp: Path) -> Path:
    """Generate a calibration workload deterministically.

    Generated rather than committed, and generated from the manifest's own
    scale, so a calibration workload can never quietly become a decisive one by
    somebody dropping a real project into a directory.
    """
    gen = str(w.spec.get("generator"))
    if gen == "refused":
        p = tmp / f"{w.id}.json"
        p.write_text(json.dumps({"ownir_version": 999_999, "module": w.id}), encoding="utf-8")
        return p
    if gen == "facts":
        scale = int(w.spec.get("scale", 1))
        doc = {
            "ownir_version": 0,
            "module": w.id,
            "components": [{"name": f"C{i}", "kind": "class", "file": f"gen/{i}.cs", "line": i + 1}
                           for i in range(scale)],
            "services": [],
            "functions": [{"name": f"F{i}", "component": f"C{i % max(scale, 1)}",
                           "file": f"gen/{i}.cs", "line": i + 2, "statements": []}
                          for i in range(scale)],
            "stats": {"generated": True, "scale": scale},
        }
        p = tmp / f"{w.id}.json"
        p.write_text(json.dumps(doc), encoding="utf-8")
        return p
    if gen == "csharp":
        scale = int(w.spec.get("scale", 1))
        d = tmp / w.id
        d.mkdir(parents=True, exist_ok=True)
        for i in range(scale):
            (d / f"Gen{i}.cs").write_text(
                "using System;\nusing System.IO;\n\n"
                f"public class Gen{i}\n{{\n"
                f"    public void Run{i}()\n    {{\n"
                f"        var s = new FileStream(\"g{i}.txt\", FileMode.OpenOrCreate);\n"
                f"        Console.WriteLine(s.Length);\n"
                "    }\n}\n", encoding="utf-8")
        return d
    raise InstrumentError(f"{w.id}: unknown calibration generator {gen!r}")


# --- the rung ladder -------------------------------------------------------


@dataclass(frozen=True)
class Rung:
    id: str
    surface: str          # "core" | "launcher"
    needs: str            # "none" | "facts" | "facts-refused" | "source"
    phases: tuple[str, ...]
    observability: str    # what this interval can and cannot say
    expect_rc: tuple[int, ...]   # the exit codes that mean THIS RUNG DID ITS JOB
    evidence: str                # the post-condition proving it, checked untimed
    why: str


RUNGS: tuple[Rung, ...] = (
    Rung("core-usage", "core", "none",
         ("process-startup-core", "cli-argv-parse", "cli-usage-refusal"), "composed",
         (2,), "usage-help",
         "The ladder FLOOR: the smallest real invocation the production surface allows — the "
         "process starts, parses argv, finds no document, writes a usage refusal and exits. It "
         "is a LOWER BOUND on core startup, not startup itself. argv handling and the refusal "
         "message are inside this interval and cannot be separated out through the production "
         "surface without instrumentation #263-A is not authorized to add. Calling it 'startup' "
         "would let a later subtraction hand D7 a phase nobody measured."),
    Rung("core-parse-refused", "core", "facts-refused",
         ("process-startup-core", "cli-argv-parse", "ownir-parse", "ownir-door-refusal"),
         "composed", (2,), "door-refusal",
         "A document the strict door refuses on its version. The read and parse happen; bridge "
         "and analysis never do. Subtracting core-usage does NOT leave parse: it leaves the "
         "ownir read+parse cost only under an assumption this instrument never measures — that "
         "both invocations pay the same argv handling, and that cli-usage-refusal and "
         "ownir-door-refusal cost the same. They are different phases writing different text on "
         "different streams, so that second assumption is visibly an assumption. "
         "The difference is therefore a DERIVED bound, labelled as such, and never presented as "
         "a direct measurement of parse."),
    Rung("core-full-human", "core", "facts",
         ("process-startup-core", "cli-argv-parse", "ownir-parse", "bridge-lowering",
          "analysis", "render-human"), "composed",
         (0, 1), "verdict-human",
         "The whole core path to the default surface. Exit 0 and exit 1 both mean a verdict was "
         "produced — 1 is 'leaks found', not a failure — and any other code means this interval "
         "timed something that is not the analysis path. bridge-lowering and analysis are not "
         "separately observable through the production surface and are recorded as members of "
         "this interval, not imputed from it."),
    Rung("core-full-sarif", "core", "facts",
         ("process-startup-core", "cli-argv-parse", "ownir-parse", "bridge-lowering",
          "analysis", "render-sarif"), "composed",
         (0, 1), "verdict-sarif",
         "The same path to the SARIF surface. Against core-full-human it gives a renderer "
         "DIFFERENCE, which is not the same quantity as rendering in isolation and is never "
         "reported as if it were."),
    Rung("launcher-e2e", "launcher", "source",
         ("process-startup-launcher", "frontend-extraction", "process-startup-core",
          "cli-argv-parse", "ownir-parse", "bridge-lowering", "analysis",
          "render-human"), "composed",
         (0,), "verdict-human",
         "The user-visible whole, through the production launcher with the engine explicitly "
         "selected. Each engine performs ITS OWN extraction: extraction is inside the elapsed "
         "time, because an end-to-end number that shares one extraction between engines is a "
         "core comparison wearing an end-to-end hat."),
)

def _evidence_problem(kind: str, out: str, err: str) -> str:
    """"" when the rung demonstrably did its job; otherwise why not.

    Each check reads what the invocation actually produced. Measured, not
    assumed: the exit codes and streams below were probed against both engines
    before being written down.
    """
    if kind == "usage-help":
        # Both engines print their driver banner to STDOUT and leave stderr
        # empty; that split is what distinguishes an argv refusal from a door
        # refusal, since both exit 2. The banner does NOT contain the word
        # "usage" — the first version of this check asserted it did and refused
        # every healthy floor cell, which is the same assume-instead-of-measure
        # habit the check exists to catch. What it does contain, in both
        # engines, is the name of the subcommand that was invoked.
        if "ownir" not in out.lower():
            return ("stdout does not name the subcommand, so this was not the argv refusal it "
                    "claims to time")
        if err.strip():
            return f"the usage path wrote to stderr ({err.strip()[:80]!r}); something else failed"
        return ""
    if kind == "door-refusal":
        if out.strip():
            return "the strict door printed a verdict on stdout; the document was not refused"
        if "error:" not in err.lower():
            return f"no refusal on stderr ({err.strip()[:80]!r}); the door did not refuse this"
        return ""
    if kind == "verdict-human":
        if not out.strip():
            return "no verdict on stdout: the pipeline did not reach a rendered result"
        return ""
    if kind == "verdict-sarif":
        try:
            doc = json.loads(out)
        except json.JSONDecodeError:
            return "stdout is not JSON, so the SARIF renderer did not produce a document"
        if not isinstance(doc, dict) or "runs" not in doc:
            return "stdout is JSON but carries no SARIF 'runs', so this is not a SARIF verdict"
        return ""
    raise InstrumentError(f"unknown rung evidence kind {kind!r}")


# WITHDRAWN: a `launcher-extract` rung claiming to stop after extraction.
#
# It invoked the launcher with `--emit-facts` and was documented as "no core
# runs, so this isolates the frontend stage". That is false, and the launcher
# says so itself: --emit-facts copies the intermediate facts and then Stage 2
# runs the engine anyway, so the interval actually contained launcher startup,
# extraction, core startup, parse, lowering, analysis AND rendering while
# recording itself as launcher startup plus extraction. That is precisely the
# defect the core-usage repair was about — an interval naming itself after a
# subset of what it contains — and a local run with no .NET on PATH hid it by
# failing at 127 before Stage 2 was ever reached.
#
# The honest options were to change the production launcher (out of scope here)
# or to measure the extractor process directly (a different surface, and a
# direct extractor invocation is not the launcher's extraction stage). So
# launcher-scoped extraction isolation is recorded as UNAVAILABLE instead of
# being invented. frontend-extraction remains measured as a member of the
# launcher-e2e interval.

# Phases named by #262's Performance-gates, plus the frontend stage the brief
# adds as a diagnostic. Recorded here so a reader can see which are gate phases
# and which are not, without inferring it from a rung id.
PHASES = {
    "process-startup-core": "user-visible? no — the child engine's own startup",
    # Split, because one name for two actions put a phase in intervals that never
    # performed it. Every real core invocation parses argv; only the floor rung
    # writes a usage refusal, and only the version-refused rung writes a door
    # refusal. A phase list has to mean "this interval did these things".
    "cli-argv-parse": "the core CLI's argument handling, before any document is opened; present "
                      "in every real core invocation",
    "cli-usage-refusal": "the driver banner a core invocation with no document writes before "
                         "exiting; unavoidably inside the floor rung, which is why that rung is "
                         "a bound on startup and not startup itself",
    "ownir-door-refusal": "the strict door's refusal message for a document it will not accept "
                          "on its version",
    "process-startup-launcher": "user-visible: what a caller waits for before anything happens",
    "ownir-parse": "the ownir document read and validate",
    "bridge-lowering": "facts -> Layer 2 -> core AST",
    "analysis": "the worklist/lattice solve",
    "render-human": "output serialization only (default surface)",
    "render-sarif": "output serialization only (SARIF surface)",
    "frontend-extraction": "C# -> facts; recorded, NOT D7-gated unless separately ratified",
}


# --- the noise floor and run invalidation (§7) -----------------------------


NOISE_PROBE_ITERATIONS = 25
# An INSTRUMENT-VALIDITY constant, not a performance budget. It says how much
# the machine may wobble before a measurement taken on it means nothing; it
# says nothing whatever about either engine, and it is not a D7 threshold.
# THREE policies, three different statistical quantities, one historical value.
#
# A single constant used to play all three roles, and the report claimed the
# reproducibility tolerance was "the noise floor recorded by the earlier run,
# not a chosen number". That was false twice over: the recorded limit IS this
# constant, so reading it back is reading the constant, and nothing about it
# tightens on a quiet machine. It is chosen. It was chosen before any of the
# runs that later failed against it, which is the only thing that makes it
# admissible at all.
#
# They are separated here so each can be argued about on its own terms. The
# VALUE is deliberately unchanged on this PR: moving a number after seeing which
# runs it rejects is a threshold fitted to a result, and that decision is not
# this change's to make.
NOISE_PROBE_MAX_RELATIVE_IQR = 0.35        # dispersion WITHIN one probe
NOISE_PROBE_MAX_DRIFT = 0.35               # opening probe vs closing probe
REPRODUCIBILITY_MAX_MEDIAN_CHANGE = 0.35   # one cell's median, run A vs run B

# Retained under its old name because the report records it and older evidence
# reads it back. It is the probe dispersion limit and nothing else.
NOISE_FLOOR_MAX_RELATIVE_IQR = NOISE_PROBE_MAX_RELATIVE_IQR


def noise_probe() -> dict[str, object]:
    """A fixed deterministic task, timed repeatedly, to size the machine's wobble.

    This is how a contended runner announces itself. A benchmark that widens its
    own dispersion rather than refusing the environment is reporting the noise
    as if it were the subject.
    """
    samples = []
    for _ in range(NOISE_PROBE_ITERATIONS):
        t0 = time.perf_counter_ns()
        acc = 0
        for i in range(200_000):
            acc = (acc + i * 2654435761) & 0xFFFFFFFF
        samples.append(time.perf_counter_ns() - t0)
    med = statistics.median(samples)
    q = statistics.quantiles(samples, n=4) if len(samples) >= 4 else [med, med, med]
    iqr = q[2] - q[0]
    return {"median_ns": med, "iqr_ns": iqr, "min_ns": min(samples),
            "relative_iqr": (iqr / med) if med else None,
            "iterations": NOISE_PROBE_ITERATIONS,
            "limit_relative_iqr": NOISE_FLOOR_MAX_RELATIVE_IQR}


def invalidation_reasons(before: dict[str, object], after: dict[str, object]) -> list[str]:
    out = []
    for label, probe in (("before", before), ("after", after)):
        rel = probe.get("relative_iqr")
        if rel is None:
            out.append(f"noise probe {label}: no median, so the floor is unknown")
        elif float(rel) > NOISE_PROBE_MAX_RELATIVE_IQR:
            out.append(f"noise probe {label}: relative IQR {float(rel):.3f} exceeds the "
                       f"{NOISE_PROBE_MAX_RELATIVE_IQR} floor — a contended or throttling runner")
    b, a = before.get("median_ns"), after.get("median_ns")
    if isinstance(b, (int, float)) and isinstance(a, (int, float)) and b:
        drift = abs(a - b) / b
        if drift > NOISE_PROBE_MAX_DRIFT:
            out.append(f"the machine drifted {drift:.3f} between the opening and closing probes")
    return out


# --- aggregation (§6) ------------------------------------------------------


def summarize(samples: list[int], unit: str = "ns") -> dict[str, object]:
    """median + dispersion + min, never mean-only. Raw is retained by the caller.

    The Rust-vs-Python comparison statistic is NOT here and must not be added
    here: how two engines' numbers become one number is D7's to preregister,
    and a helper that quietly offered a ratio would be choosing it.
    """
    if not samples:
        return {"n": 0}
    med = statistics.median(samples)
    out: dict[str, object] = {
        "n": len(samples),
        f"median_{unit}": med,
        f"min_{unit}": min(samples),
        f"mad_{unit}": statistics.median([abs(s - med) for s in samples]),
    }
    if len(samples) >= 4:
        q = statistics.quantiles(samples, n=4)
        out[f"iqr_{unit}"] = q[2] - q[0]
        out[f"q1_{unit}"], out[f"q3_{unit}"] = q[0], q[2]
    return out


# --- the single place a clock starts ---------------------------------------


@dataclass
class Harness:
    gate: IdentityGate
    session: SessionIdentity
    rss: RssProbe
    tmp: Path
    candidate: Path
    warmup_discards: int
    repetitions: int
    seed: int
    execution_order: list[str] = field(default_factory=list)
    raw: list[dict[str, object]] = field(default_factory=list)

    # -- the firewall ------------------------------------------------------

    def _assert_may_time(self, w: Workload) -> None:
        """The one gate every timed measurement passes through.

        Deliberately stricter than "no PAIRED timed runs": a single-engine timed
        run of a decisive workload is refused too. The brief's permitted list for
        a decisive workload before the freeze is enumerate / hash / fetch /
        availability-check / non-timed structural smoke, and a stopwatch appears
        nowhere in it.
        """
        if w.decisive and not self.gate.armed:
            raise FirewallBreach(
                f"refusing to time the DECISIVE workload {w.id!r}: the D7 freeze has not "
                f"happened ({self.gate.reason}). Before the freeze a decisive workload may be "
                "enumerated, hashed, fetched, availability-checked and smoke-tested without a "
                "clock — nothing else. This is not a policy that can be waived from the command "
                "line; arming the gate requires a verified D7 attestation.")

    # -- one measured interval ---------------------------------------------

    def _run_once(self, argv: list[str], env: dict[str, str], cwd: Path) -> dict[str, object]:
        """Spawn, time, and read peak RSS. Nothing hashed, nothing verified here.

        Every identity check has already run and passed by the time this is
        called: the notary's cost belongs outside the interval it protects.
        """
        wrapped, sidecar = self.rss.wrap(argv, self.tmp)
        job = None
        if os.name == "nt" and self.rss.mechanism.startswith("win32"):
            job = ctypes.windll.kernel32.CreateJobObjectW(None, None)  # type: ignore[attr-defined]
        peak: int | None = None
        why = ""
        t0 = time.perf_counter_ns()
        proc = subprocess.Popen(wrapped, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                env=env, cwd=str(cwd))
        if job:
            ctypes.windll.kernel32.AssignProcessToJobObject(  # type: ignore[attr-defined]
                job, int(proc._handle))  # type: ignore[attr-defined]
        if self.rss.mechanism.startswith("posix"):
            # Reap through wait4 so the kernel hands back THIS child's rusage.
            _, status, ru = os.wait4(proc.pid, 0)
            proc.returncode = os.waitstatus_to_exitcode(status)
            rc = proc.returncode
            elapsed = time.perf_counter_ns() - t0
            peak = int(ru.ru_maxrss) * self.rss.maxrss_unit_bytes
        else:
            rc = proc.wait()
            elapsed = time.perf_counter_ns() - t0
            peak = self.rss.read(sidecar)
            if peak is None and job:
                peak, why = self.rss.read_windows_peak(job)
        if job:
            ctypes.windll.kernel32.CloseHandle(job)  # type: ignore[attr-defined]
        if sidecar is not None and sidecar.is_file():
            sidecar.unlink()
        return {"elapsed_ns": elapsed, "rc": rc, "peak_rss_bytes": peak,
                "rss_unavailable_reason": why or (self.rss.reason if peak is None else "")}

    # -- non-timed structural smoke (permitted on decisive workloads) ------

    def smoke(self, w: Workload, path: Path | None) -> dict[str, object]:
        """Availability and shape, with no clock and no resource sampling.

        Returns no duration field at all — not a null one. A smoke result that
        carried an empty timing slot would be one careless edit away from being
        filled in.
        """
        present = path is not None and path.exists()
        out: dict[str, object] = {"workload": w.id, "population": w.population,
                                  "present": present, "tag": CALIBRATION_ONLY}
        if present and path is not None and path.is_file():
            digest, n = sha256_file(path)
            out["sha256"], out["bytes"] = digest, n
        elif present and path is not None:
            files = sorted(p for p in path.rglob("*.cs"))
            out["cs_files"] = len(files)
        return out

    # -- cells and the seeded interleave -----------------------------------

    def argv_for(self, rung: Rung, engine: str,
                 target: Path | None) -> tuple[list[str], dict[str, str], Path]:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT)
        env["OWEN_RUST_CORE"] = str(self.candidate)
        if rung.surface == "core":
            base = ([sys.executable, "-m", "ownlang", "ownir"] if engine == "python"
                    else [str(self.candidate), "ownir"])
            if rung.needs == "none":
                return base, env, ROOT
            assert target is not None
            fmt = "sarif" if rung.id.endswith("sarif") else "human"
            return [*base, str(target), "--format", fmt], env, ROOT
        # launcher surface — the production shell entry point, both engines
        sh = str(ROOT / "scripts/own-check.sh")
        assert target is not None
        return [_bash(), sh, "--engine", engine, "--format", "human", "--", str(target)], env, ROOT

    def verify_outcome(self, rung: Rung, argv: list[str], env: dict[str, str],
                       cwd: Path) -> dict[str, object]:
        """Did this rung actually do the work it claims to time? Asked ONCE, untimed.

        The instrument previously recorded whatever the process did and summarised
        it. With no .NET on PATH the launcher rungs exited 127 before doing
        anything at all, and 12 of 44 cells reproducibly measured a
        command-not-found path while the report called them reproduced. An exit
        code nobody checked is not a measurement, it is a number.

        This runs outside every measured interval — with output captured, which
        the timed path deliberately does not do — so its cost never reaches a
        benchmark.
        """
        r = subprocess.run(argv, capture_output=True, env=env, cwd=str(cwd), check=False,
                           timeout=1800)
        out = r.stdout.decode("utf-8", "replace")
        err = r.stderr.decode("utf-8", "replace")
        problems = []
        if r.returncode not in rung.expect_rc:
            problems.append(
                f"exit {r.returncode}, but {rung.id} does its job only at "
                f"{sorted(rung.expect_rc)}"
                + (" — 127 is command-not-found, so the rung never ran"
                   if r.returncode == 127 else ""))
        why = _evidence_problem(rung.evidence, out, err)
        if why:
            problems.append(why)
        return {"expected_exit_codes": sorted(rung.expect_rc), "observed_exit_code": r.returncode,
                "evidence": rung.evidence, "valid": not problems, "problems": problems}

    def measure_cell(self, rung: Rung, engine: str, w: Workload, target: Path | None,
                     regime: str) -> dict[str, object]:
        """One (rung x engine x workload x regime) cell. Identity first, clock second."""
        self._assert_may_time(w)
        self.session.reverify()          # outside every interval, by construction
        argv, env, cwd = self.argv_for(rung, engine, target)

        # Outcome BEFORE clock. A cell whose invocation did not do the rung's
        # work is not timed at all: timing a failure path and reporting its
        # dispersion is how 12 command-not-found cells once passed as a
        # reproduced calibration.
        outcome = self.verify_outcome(rung, argv, env, cwd)
        if not outcome["valid"]:
            return {
                "rung": rung.id, "engine": engine, "workload": w.id, "regime": regime,
                "phases": list(rung.phases), "observability": rung.observability,
                "argv": ([*argv[:1], "<...>"] if rung.surface == "core"
                         else [*argv[:2], "<...>"]),
                "outcome": outcome,
                "timing": None, "peak_rss": None, "raw_elapsed_ns": [],
                "not_timed_because": "the rung did not do its work; measuring it would time "
                                     "the wrong path",
                "tag": CALIBRATION_ONLY,
            }

        discarded = []
        for _ in range(self.warmup_discards if regime == "warm" else 0):
            discarded.append(self._run_once(argv, env, cwd))
        samples: list[dict[str, object]] = []
        for _ in range(self.repetitions):
            samples.append(self._run_once(argv, env, cwd))
            self.session.measurements_taken += 1

        rcs = sorted({int(s["rc"]) for s in samples})  # type: ignore[arg-type]
        # Every timed sample must also land on a declared code. The untimed
        # verification proved the rung CAN do its work; this proves each timed
        # iteration actually did.
        stray = [c for c in rcs if c not in rung.expect_rc]
        if stray:
            outcome = {**outcome, "valid": False,
                       "problems": [*list(outcome["problems"]),  # type: ignore[list-item]
                                    f"timed iterations exited {stray}, outside "
                                    f"{sorted(rung.expect_rc)}"]}
        cell = {
            "rung": rung.id, "engine": engine, "workload": w.id, "regime": regime,
            "phases": list(rung.phases), "observability": rung.observability,
            "outcome": outcome,
            "argv": ([*argv[:1], "<...>"] if rung.surface == "core"
                     else [*argv[:2], "<...>"]),
            "exit_codes": rcs,
            "warmup_discarded": len(discarded),
            "timing": summarize([int(s["elapsed_ns"]) for s in samples]),  # type: ignore[arg-type]
            "peak_rss": summarize(
                [int(s["peak_rss_bytes"]) for s in samples if s["peak_rss_bytes"] is not None],
                unit="bytes"),
            "rss_mechanism": self.rss.mechanism,
            "rss_unavailable_reason": next(
                (str(s["rss_unavailable_reason"]) for s in samples
                 if s["peak_rss_bytes"] is None and s["rss_unavailable_reason"]), ""),
            "raw_elapsed_ns": [int(s["elapsed_ns"]) for s in samples],  # §9: raw retained
            "raw_peak_rss_bytes": [s["peak_rss_bytes"] for s in samples],
            "tag": CALIBRATION_ONLY,
        }
        return cell

    def run_calibration(self, workloads: list[Workload]) -> list[dict[str, object]]:
        """Every cell, interleaved under the recorded seed.

        Interleaved rather than blocked: run all of Python and then all of Rust
        and the machine's own drift becomes an engine difference. The actual
        order is retained, because a randomization nobody can replay is a fond
        memory rather than a method.
        """
        rng = random.Random(self.seed)
        materialized: dict[str, Path] = {}
        for w in workloads:
            materialized[w.id] = materialize_calibration(w, self.tmp)

        cells: list[tuple[Rung, str, Workload, str]] = []
        for rung in RUNGS:
            for w in workloads:
                if not _rung_accepts(rung, w):
                    continue
                for engine in ("python", "rust"):
                    for regime in ("process-cold", "warm"):
                        cells.append((rung, engine, w, regime))

        results: list[dict[str, object]] = []
        order = list(cells)
        rng.shuffle(order)
        for rung, engine, w, regime in order:
            key = f"{rung.id}|{engine}|{w.id}|{regime}"
            self.execution_order.append(key)
            target = materialized.get(w.id) if rung.needs != "none" else None
            results.append(self.measure_cell(rung, engine, w, target, regime))
        return results


def _bash() -> str:
    """The bash that can run own-check.sh — never WSL's System32 stub on Windows."""
    if os.name != "nt":
        return "bash"
    for c in (os.environ.get("SHELL"), r"C:\Program Files\Git\bin\bash.exe",
              r"C:\Program Files\Git\usr\bin\bash.exe"):
        if c and Path(c).is_file():
            return c
    return "bash"


def _rung_accepts(rung: Rung, w: Workload) -> bool:
    if rung.needs == "none":
        return w.id.endswith("facts-tiny")      # one representative; startup has no workload
    if rung.needs == "facts":
        return w.kind == "generated-facts" and w.spec.get("generator") == "facts"
    if rung.needs == "facts-refused":
        return w.spec.get("generator") == "refused"
    if rung.needs == "source":
        return w.kind in ("generated-source", "source-tree")
    return False


# --- the reference identity -------------------------------------------------


# The Python reference source. Its identity is a property of THIS directory, not
# of the repository's current position.
PYTHON_REFERENCE_PATH = "ownlang"


def python_reference_commit(root: Path = ROOT) -> str:
    """§12: the decisive measurement and the G3 correctness evidence must name the
    SAME Python reference state, by commit SHA.

    This used to return ``git rev-parse HEAD``, which is not the reference — it
    is wherever the repository happens to be standing. Every commit moved it,
    including commits that only added evidence, so run A and run B of one pair
    recorded two different "reference" identities while ownlang had not changed
    a byte. Worse, at D7 the freeze creates a C1 commit and then a C2 commit, so
    a correctly executed freeze would itself invalidate the reference binding it
    had just written down: an alarm that counts its own installation as a
    break-in.

    The reference commit is now the last commit that TOUCHED the reference
    source. It moves when ownlang moves and at no other time.
    """
    rc, out = _git_in(root, "log", "-1", "--format=%H", "--", PYTHON_REFERENCE_PATH)
    return out if rc == 0 else ""


def python_reference_tree(root: Path = ROOT) -> str:
    """The reference's CONTENT identity: the git tree object of ownlang.

    Content-addressed, so it is identical across two checkouts that hold the
    same reference source regardless of history. Recorded beside the commit sha
    as a cross-check — a commit sha alone cannot show that two artifacts saw the
    same bytes, only that they named the same label.
    """
    rc, out = _git_in(root, "rev-parse", f"HEAD:{PYTHON_REFERENCE_PATH}")
    return out if rc == 0 else ""


# --- report ----------------------------------------------------------------


def build_report(harness: Harness, cells: list[dict[str, object]],
                 manifest_digest: str, before: dict[str, object],
                 after: dict[str, object], workloads: list[Workload],
                 smoke: list[dict[str, object]]) -> dict[str, object]:
    invalid = invalidation_reasons(before, after)
    return {
        "schema": 1,
        "tag": CALIBRATION_ONLY,
        "not_decision_evidence": (
            "CALIBRATION ONLY. These numbers validate the INSTRUMENT and are not evidence about "
            "either engine. They cannot choose a threshold, a budget, a repetition count or a "
            "comparison statistic; those are D7's, frozen before the decisive run. No decisive "
            "workload was timed or resource-sampled to produce this file."),
        "harness": {
            "version": HARNESS_VERSION,
            "digest": harness_digest(),
            "warmup_discards": harness.warmup_discards,
            "calibration_repetitions": harness.repetitions,
            "repetitions_note": (
                "a CALIBRATION parameter for sizing the instrument, not the decisive N. The "
                "decisive N and its escalation ladder are preregistered by D7."),
            "seed": harness.seed,
            "execution_order": harness.execution_order,
        },
        "identity": {
            "gate_armed": harness.gate.armed,
            "gate_reason": harness.gate.reason,
            "gate_observed": harness.gate.observed,
            # What a payload must survive to arm this gate, written into the
            # evidence so the report describes its own verifier instead of
            # asking a reader to take the harness on trust.
            "gate_requirements": IdentityGate.requirements(),
            # Empty while dormant. Never carries a C2 VALUE — only which C2
            # fields were present — because a #263-A artifact that quoted a
            # threshold would have leaked the number this module exists to
            # keep out.
            "gate_pinned": harness.gate.pinned,
            "session_candidate": {
                "path": harness.session.path,
                "sha256": harness.session.sha256,
                "bytes": harness.session.bytes_len,
                "frozen_at": harness.session.frozen_at,
                "measurements_taken": harness.session.measurements_taken,
            },
        },
        "provenance": {
            "tree_sha": _git("rev-parse", "HEAD"),
            "tree_dirty": bool(_git("status", "--porcelain")),
            "python_reference_commit": python_reference_commit(),
            "python_reference_tree": python_reference_tree(),
            "python_interpreter": sys.version.split()[0],
            "workload_manifest_sha256": manifest_digest,
            "environment": environment_fingerprint(),
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "regimes": {
            "process-cold": "a fresh process every iteration, no in-process warmup. The default: "
                            "cheap, portable, and honestly named.",
            "warm": f"steady state after {harness.warmup_discards} DISCARDED iterations of the "
                    "same cell. The process is still fresh each time; what is warm is the OS "
                    "and filesystem cache.",
            "machine-cold": "NOT CLAIMED here. It exists only behind a documented reset protocol "
                            "(cache drop / reboot / fresh VM), and 'caches not pre-warmed' with "
                            "no reset step means a different kind of cold on Windows than on "
                            "Linux. A machine-cold claim without its reset protocol is "
                            "inadmissible, so this instrument does not make one.",
        },
        "noise": {"before": before, "after": after,
                  "invalidated": bool(invalid), "invalidation_reasons": invalid},
        "phases": PHASES,
        "rungs": [{"id": r.id, "surface": r.surface, "phases": list(r.phases),
                   "observability": r.observability, "expect_rc": list(r.expect_rc),
                   "evidence": r.evidence, "why": r.why} for r in RUNGS],
        "unobservable_phases": {
            "bridge-lowering": "not separately observable through either engine's production "
                               "surface; recorded as a member of the core-full-* interval.",
            "analysis": "same — isolating it would need production instrumentation, which "
                        "#263-A is not authorized to add.",
            "frontend-extraction (launcher-scoped isolation)":
                "UNAVAILABLE. The launcher's --emit-facts copies the intermediate facts and then "
                "runs the engine anyway, so an interval built on it contains the whole pipeline "
                "and cannot isolate extraction. Isolating it would need either a production "
                "launcher change or a direct extractor invocation, which is a different surface "
                "and not the launcher's extraction stage. Recorded as unavailable rather than "
                "invented; frontend-extraction is still measured as a member of launcher-e2e.",
        },
        # A cell is only a measurement if the invocation did the rung's work.
        # This block is the verdict on that, separate from whether the machine
        # was quiet enough (that is "noise" above).
        "outcomes": {
            "valid": all((c.get("outcome") or {}).get("valid") for c in cells),
            "cells_timed": sum(1 for c in cells if c.get("timing")),
            "cells_refused": sum(1 for c in cells if not (c.get("outcome") or {}).get("valid")),
            "problems": [f"{c['rung']}|{c['engine']}|{c['workload']}|{c['regime']}: "
                         + "; ".join((c.get("outcome") or {}).get("problems") or [])
                         for c in cells if not (c.get("outcome") or {}).get("valid")],
            "contract": {r.id: {"expected_exit_codes": sorted(r.expect_rc),
                                "evidence": r.evidence} for r in RUNGS},
        },
        "workload_populations": {
            "decisive": [w.id for w in workloads if w.decisive],
            "calibration": [w.id for w in workloads if not w.decisive],
        },
        "decisive_smoke": smoke,
        "cells": cells,
    }


def _git(*args: str) -> str:
    r = subprocess.run(["git", *args], capture_output=True, cwd=str(ROOT), check=False)
    return r.stdout.decode("utf-8", "replace").strip() if r.returncode == 0 else ""


# --- selftest ---------------------------------------------------------------


# Whole TOKENS, never substrings. The first version matched substrings and
# promptly refused its own report: "calibration" and "iterations" both contain
# "ratio". Reading a proxy for the thing is the failure mode this project keeps
# rediscovering, and a key vocabulary is exactly where it hides.
COMPARISON_TOKENS = frozenset({
    "delta", "deltas", "ratio", "ratios", "speedup", "slowdown", "versus", "vs",
    "faster", "slower", "improvement", "regression",
})


def _key_tokens(key: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", key.lower()) if t}


def engine_comparison_problems(report: dict[str, object]) -> list[str]:
    """The instrument records each engine's own numbers and nothing derived from
    both. How two engines' numbers become one number is D7's to preregister, so
    a helper that quietly offered it here would be choosing it.

    Two structural rules, read off the report itself:
      * every cell names exactly ONE engine and carries samples from that engine;
      * no key anywhere in the report belongs to the comparison vocabulary.
    """
    problems: list[str] = []
    cells = report.get("cells")
    if isinstance(cells, list):
        for i, cell in enumerate(cells):
            if not isinstance(cell, dict):
                continue
            engine = cell.get("engine")
            if not isinstance(engine, str) or not engine:
                problems.append(f"cell {i} names no engine")
            others = [k for k in cell
                      if isinstance(k, str) and any(e in k for e in ("python", "rust"))]
            if others:
                problems.append(f"cell {i} ({engine}) carries engine-named keys {others}: a cell "
                                "holds one engine's samples, never a comparison")

    def walk(node: object, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if _key_tokens(str(k)) & COMPARISON_TOKENS:
                    problems.append(f"{path}.{k}: an engine-comparison key — that statistic is "
                                    "D7's, frozen before the decisive run, and is not this "
                                    "instrument's to invent")
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(report, "report")
    return problems


# Everything two halves of a pair must agree on. A "reproduced" verdict compares
# one run against another; if they were measured against different source, a
# different reference, a different candidate binary or a different workload
# manifest, the comparison is between two different experiments and the word
# means nothing.
#
# This list is why it exists: run A and run B once diverged on tree_sha and
# python_reference_commit, because A was COMMITTED before B was measured and
# python_reference_commit() is `git rev-parse HEAD`. Committing evidence between
# the halves moved the recorded reference identity while ownlang had not
# changed at all. The procedure is now: measure both halves on ONE clean commit,
# writing outside the repository, verify identity, then commit both together.
PAIR_IDENTITY_FIELDS = (
    "tree_sha", "tree_dirty", "python_reference_commit", "python_reference_tree",
    "workload_manifest_sha256", "harness_digest", "calibration_repetitions",
    "warmup_discards", "candidate_sha256", "candidate_bytes",
)


def _pair_identity(report: dict[str, object]) -> dict[str, object]:
    prov = report.get("provenance") or {}
    harn = report.get("harness") or {}
    cand = ((report.get("identity") or {}).get("session_candidate") or {})  # type: ignore[union-attr]
    return {
        "tree_sha": str(prov.get("tree_sha", "")),                    # type: ignore[union-attr]
        "tree_dirty": prov.get("tree_dirty"),                         # type: ignore[union-attr]
        "python_reference_commit": str(prov.get("python_reference_commit", "")),  # type: ignore[union-attr]
        "python_reference_tree": str(prov.get("python_reference_tree", "")),  # type: ignore[union-attr]
        "workload_manifest_sha256": str(prov.get("workload_manifest_sha256", "")),  # type: ignore[union-attr]
        "harness_digest": str(harn.get("digest", "")),                # type: ignore[union-attr]
        "calibration_repetitions": harn.get("calibration_repetitions"),  # type: ignore[union-attr]
        "warmup_discards": harn.get("warmup_discards"),               # type: ignore[union-attr]
        "candidate_sha256": str(cand.get("sha256", "")),
        "candidate_bytes": cand.get("bytes"),
    }


def reproduce(previous: Path, current: dict[str, object]) -> dict[str, object]:
    """§9: a second run on the same environment reproduces the first WITHIN §7's policy.

    Not byte-identical — a report carries timestamps and an execution order, and
    demanding byte equality would only prove the clock was frozen. What must
    agree is each cell's median, within REPRODUCIBILITY_MAX_MEDIAN_CHANGE.

    That tolerance is a CHOSEN policy constant. This docstring used to say it was
    "the noise floor the run itself recorded", so the check "tightens on a quiet
    machine" — both false. It never tightened: the recorded limit was the same
    constant, read back out of JSON and returning disguised as a measurement.
    What makes the constant admissible is that it was chosen before the runs it
    judges, not that it was derived from them.

    The EARLIER run's identity is recorded in the result. A verdict of
    "reproduced" that names only one of the two runs cannot be recomputed by
    anyone but the program that already reached it.
    """
    raw_previous = previous.read_bytes()
    old = json.loads(raw_previous.decode("utf-8"))

    # Fail-closed BEFORE comparing anything. A mismatched pair should not be
    # producible, not merely detectable afterwards by a control reading the
    # shipped files.
    mine, theirs = _pair_identity(current), _pair_identity(old)
    differ = [k for k in PAIR_IDENTITY_FIELDS if mine[k] != theirs[k]]
    if differ:
        raise InstrumentError(
            "the two halves of this pair were not measured under one identity, so comparing "
            "them would compare two different experiments: "
            + "; ".join(f"{k} {theirs[k]!r} then {mine[k]!r}" for k in differ)
            + ". Measure both halves on one clean commit, writing outside the repository, and "
              "commit them together.")
    # The POLICY constant, named for the quantity it bounds. Previously this read
    # the probe's recorded limit back out of the earlier report, which is the
    # same constant taking a detour through JSON and arriving disguised as a
    # measurement.
    tol = REPRODUCIBILITY_MAX_MEDIAN_CHANGE
    old_cells = {(c["rung"], c["engine"], c["workload"], c["regime"]): c
                 for c in old.get("cells", [])}
    new_cells = {(c["rung"], c["engine"], c["workload"], c["regime"]): c
                 for c in current.get("cells", [])}
    missing = sorted(set(old_cells) - set(new_cells))
    added = sorted(set(new_cells) - set(old_cells))
    disagreed = []
    outcome_changed = []
    for key in sorted(set(old_cells) & set(new_cells)):
        # Outcome identity first. Two runs that agree to the nanosecond while
        # exiting differently did not reproduce a measurement, they reproduced a
        # coincidence — and if both ran the wrong path, agreeing about it is the
        # worst possible reassurance.
        oa = old_cells[key].get("outcome") or {}
        ob = new_cells[key].get("outcome") or {}
        if oa.get("observed_exit_code") != ob.get("observed_exit_code") or \
                bool(oa.get("valid")) != bool(ob.get("valid")):
            outcome_changed.append({
                "cell": "|".join(key),
                "earlier": {"exit": oa.get("observed_exit_code"), "valid": oa.get("valid")},
                "later": {"exit": ob.get("observed_exit_code"), "valid": ob.get("valid")}})
            continue
        if not ob.get("valid"):
            continue          # an invalid cell was never timed; nothing to compare
        a = (old_cells[key].get("timing") or {}).get("median_ns")
        b = (new_cells[key].get("timing") or {}).get("median_ns")
        if not a or not b:
            disagreed.append({"cell": "|".join(key), "why": "a run produced no median"})
            continue
        rel = abs(b - a) / a
        if rel > tol:
            disagreed.append({"cell": "|".join(key), "relative_change": rel, "tolerance": tol})
    return {
        "tag": CALIBRATION_ONLY,
        # Run A, named and hashed. Both halves of the pair are committed, so the
        # verdict below can be recomputed from evidence instead of trusted.
        "earlier_run": {
            "path": previous.name,
            "sha256": sha256_bytes(raw_previous),
            "bytes": len(raw_previous),
            **_pair_identity(old),
        },
        "compared_cells": len(set(old_cells) & set(new_cells)),
        "tolerance_relative": tol,
        "tolerance_source": ("REPRODUCIBILITY_MAX_MEDIAN_CHANGE, a fixed policy constant. It is "
                             "CHOSEN, not derived from this run; what makes it admissible is that "
                             "it was chosen before the runs it judges, and it is not adjusted "
                             "after seeing which of them it rejects."),
        "cells_only_in_earlier": ["|".join(k) for k in missing],
        "cells_only_in_later": ["|".join(k) for k in added],
        "cells_outside_tolerance": disagreed,
        "cells_whose_outcome_changed": outcome_changed,
        # TWO axes here, a third alongside in the report's admissibility block.
        #
        # outcomes_reproduced — both runs did the same work: the same cells
        #   exist and each one's outcome is identical. A disagreement is a defect
        #   in THIS HARNESS.
        # timings_reproduced — the medians agree within the policy. A
        #   disagreement says the numbers did not settle, and does NOT by itself
        #   say why: it can be a contended runner, a genuinely variable
        #   workload, or a median estimate that is simply uncertain at this
        #   repetition count. Naming it "the environment" would be asserting one
        #   of three causes without evidence.
        # environment_valid — the noise probe's own verdict, recorded in the
        #   report's noise block and carried into admissibility.
        #
        # `reproduced` keeps the meaning it has always had: everything agreed.
        # It is the conjunction of the two axes above, NOT a renamed subset —
        # a red result must not vanish because a word changed profession.
        #
        # The tolerance is untouched by this split.
        "outcomes_reproduced": not (missing or added or outcome_changed),
        "timings_reproduced": not disagreed,
        "reproduced": not (missing or added or disagreed or outcome_changed),
    }


def selftest() -> int:
    """Instrument checks that take no measurement at all."""
    problems: list[str] = []
    workloads, digest = load_manifest()
    if not any(w.decisive for w in workloads):
        problems.append("the manifest declares no decisive workloads")
    if not any(not w.decisive for w in workloads):
        problems.append("the manifest declares no calibration workloads")

    gate = IdentityGate.load(digest, python_reference_commit())
    if gate.armed:
        problems.append("the identity gate is ARMED: a D7 attestation is present, which #263-A "
                        "must never produce")

    # The firewall, exercised rather than asserted.
    with tempfile.TemporaryDirectory(prefix="perf-selftest-") as td:
        h = Harness(gate=gate, session=SessionIdentity("", "", 0, ""), rss=RssProbe(),
                    tmp=Path(td), candidate=Path("/nonexistent"), warmup_discards=1,
                    repetitions=1, seed=0)
        for w in workloads:
            try:
                h._assert_may_time(w)
            except FirewallBreach:
                if not w.decisive:
                    problems.append(f"{w.id}: a calibration workload was refused")
            else:
                if w.decisive:
                    problems.append(f"{w.id}: a DECISIVE workload was admitted to a timed path "
                                    "with the gate unarmed — the firewall does not hold")

    # The instrument must not EMIT an engine comparison. Checked on the report's
    # structure rather than on the module's prose: the first version of this
    # guard grepped the source for "ratio" and duly fired on the sentence
    # explaining why there must not be one — a validator reading a proxy instead
    # of the thing, which is the exact defect this project keeps paying for.
    problems.extend(engine_comparison_problems({
        "cells": [{"engine": "python", "timing": {"median_ns": 1}},
                  {"engine": "rust", "timing": {"median_ns": 2}}],
    }))

    for p in problems:
        print(f"FAIL[perf-instrument]: {p}")
    if not problems:
        print(f"ok[perf-instrument]: manifest {digest[:12]}…, "
              f"{sum(1 for w in workloads if w.decisive)} decisive / "
              f"{sum(1 for w in workloads if not w.decisive)} calibration workloads, "
              f"gate dormant ({gate.reason.split(':')[0]}), firewall refuses every decisive "
              f"workload, harness digest {harness_digest()[:12]}…")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="#263-A measurement instrument (calibration only)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--smoke-decisive", action="store_true")
    ap.add_argument("--candidate", default=os.environ.get("OWEN_RUST_CORE", ""))
    ap.add_argument("--repeat", type=int, default=DEFAULT_CALIBRATION_REPETITIONS,
                    help="CALIBRATION repetitions per cell. Not the decisive N.")
    ap.add_argument("--warmup", type=int, default=DEFAULT_WARMUP_DISCARDS,
                    help="discarded warmup iterations")
    ap.add_argument("--seed", type=int, default=20260910)
    ap.add_argument("--out", default="")
    ap.add_argument("--reproduce", default="",
                    help="an earlier CALIBRATION report; re-run and check §9 reproducibility")
    a = ap.parse_args(argv)

    if a.selftest:
        return selftest()

    workloads, digest = load_manifest()
    gate = IdentityGate.load(digest, python_reference_commit())

    if a.smoke_decisive:
        rows = []
        for w in workloads:
            if not w.decisive:
                continue
            p = ROOT / str(w.spec.get("path", ""))
            rows.append({"workload": w.id, "population": w.population,
                         "declared_path": str(w.spec.get("path", "")),
                         "present": p.exists(),
                         "pin": w.spec.get("pin"), "tag": CALIBRATION_ONLY})
        print(json.dumps({"tag": CALIBRATION_ONLY, "decisive_smoke": rows,
                          "note": "availability and pins only; no clock, no resource sampling"},
                         indent=2))
        return 0

    if not a.calibrate:
        ap.error("choose --selftest, --calibrate or --smoke-decisive")

    candidate = Path(a.candidate)
    if not candidate.is_file():
        raise InstrumentError(
            "--candidate / OWEN_RUST_CORE must name the production own-cli binary. The "
            "instrument never discovers it: D3's locator contract is the launcher's, and a "
            "benchmark that found its own binary would be measuring whichever one it found.")

    session = SessionIdentity.freeze(candidate)
    before = noise_probe()
    with tempfile.TemporaryDirectory(prefix="perf-cal-") as td:
        h = Harness(gate=gate, session=session, rss=RssProbe(), tmp=Path(td),
                    candidate=candidate, warmup_discards=a.warmup, repetitions=a.repeat,
                    seed=a.seed)
        cal = [w for w in workloads if not w.decisive]
        cells = h.run_calibration(cal)
        smoke = [{"workload": w.id, "present": (ROOT / str(w.spec.get("path", ""))).exists(),
                  "pin": w.spec.get("pin"), "tag": CALIBRATION_ONLY}
                 for w in workloads if w.decisive]
        after = noise_probe()
        report = build_report(h, cells, digest, before, after, workloads, smoke)

    # Fail-closed on the way OUT as well as on the way in: nothing this
    # instrument writes may be an engine comparison.
    emitted = engine_comparison_problems(report)
    if emitted:
        raise InstrumentError("the report would have carried an engine comparison: "
                              + "; ".join(emitted))

    if a.reproduce:
        report["reproducibility"] = reproduce(Path(a.reproduce), report)

    # The three axes, together, decide whether this report may be evidence of
    # record. A CI leg proving the instrument stands up may pass without them;
    # a committed calibration may not.
    rep_block = report.get("reproducibility")
    report["admissibility"] = {
        "outcomes_reproduced": (rep_block or {}).get("outcomes_reproduced"),
        "timings_reproduced": (rep_block or {}).get("timings_reproduced"),
        "environment_valid": not report["noise"]["invalidated"],  # type: ignore[index]
        "admissible": bool(rep_block
                           and rep_block.get("outcomes_reproduced")
                           and rep_block.get("timings_reproduced")
                           and not report["noise"]["invalidated"]),  # type: ignore[index]
        "note": ("all three axes are required for a report of record. A run that fails "
                 "timings_reproduced has not established WHY: a contended runner, a variable "
                 "workload and an uncertain median estimate all look the same here."),
    }

    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"wrote {a.out} ({len(cells)} cells, {CALIBRATION_ONLY})")
    else:
        print(text)
    outcomes = report["outcomes"]  # type: ignore[index]
    if not outcomes["valid"]:  # type: ignore[index]
        print("CALIBRATION REFUSED — cells whose invocation did not do the rung's work:",
              file=sys.stderr)
        for problem in outcomes["problems"]:  # type: ignore[index]
            print(f"  {problem}", file=sys.stderr)
        print("These were not timed. A report that summarised them would be measuring the "
              "wrong path and calling the agreement reproducibility.", file=sys.stderr)
        return 1
    if report["noise"]["invalidated"]:  # type: ignore[index]
        print("RUN INVALIDATED: " + "; ".join(report["noise"]["invalidation_reasons"]),  # type: ignore[index]
              file=sys.stderr)
        return 1
    rep = report.get("reproducibility")
    if isinstance(rep, dict) and not rep["outcomes_reproduced"]:
        print(f"THE INSTRUMENT DID NOT REPRODUCE ITSELF: cells only in the earlier run "
              f"{rep['cells_only_in_earlier']}, only in the later run "
              f"{rep['cells_only_in_later']}, outcome changed "
              f"{rep['cells_whose_outcome_changed']}", file=sys.stderr)
        return 1
    if isinstance(rep, dict) and not rep["timings_reproduced"]:
        print(f"TIMINGS DID NOT REPRODUCE: every outcome was identical, but these medians moved "
              f"outside the policy: {rep['cells_outside_tolerance']}. This does not say why — a "
              "contended runner, a variable workload and an uncertain median estimate are "
              "indistinguishable from here. Recorded, and the tolerance is not raised to hide "
              "it.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
