#!/usr/bin/env python3
"""Round 7's measurement runner — CALIBRATION_ONLY.

One transaction, in this order and no other:

    bind work iterations to the Round 6 2 ms rung
            v
    build arm A and arm B ONCE
            v
    B1-B4 on THOSE EXACT FILES
            v
    freeze sha256 and byte length of A, B and C
            v
    [plan mode stops here, before any clock]
            v
    time THOSE SAME FILES, re-verifying identity before every block
            v
    re-verify identity after the last block

The order is the point. The committed preflight proves properties of specific
bytes; a runner that preflighted, discarded its temporary directory, rebuilt and
then measured would be proving things about one pair of arms and timing a
different pair that happened to share their names. That is this project's
oldest and favourite genre of defect and it does not get a sequel.

Plan mode is not a flag that skips the timing loop -- it returns before the
timing function is ever reachable, and `round7-execution-contract` counts calls
to that function rather than trusting this sentence.

    python scripts/round7/runner.py --candidate <own-cli> --plan --out <json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import preflight as pf
import schedule as sch
from elfread import Elf64

if TYPE_CHECKING:
    import perf_baseline as pb

ROOT = Path(__file__).resolve().parent.parent.parent
SCALES = ROOT / "docs/evidence/round6/p022-263a-round6-scales.linux.json"
TARGET_RUNG_MS = 2
WARMUP_DISCARDS = 2          # policy, not a knob: `warm` discards two, cold none
TAG = "CALIBRATION_ONLY"


class ExecutionContractBreach(Exception):
    """The round was asked to measure something it did not preflight.

    Every breach carries structured `detail` so the abort record names the exact
    spawn or the exact arm, rather than a sentence someone would have to parse.
    One base class and one catch boundary: an invalid run leaves the same shaped
    black box whichever contract it broke.
    """

    kind = "execution-contract"

    def detail(self) -> dict[str, object]:
        return {}


class OutcomeContractBreach(ExecutionContractBreach):
    """A timed process did not do the work its arm exists to do.

    Raised on the FIRST stray, not after finishing the half. Once a contract
    breach is known, spawning more processes measures nothing anyone may use.
    """

    kind = "outcome-contract"

    def __init__(self, stray: dict[str, object]) -> None:
        self.stray = stray
        super().__init__(
            f"{stray['block']} {stray['arm']}/{stray['half']} {stray['spawn_kind']} "
            f"#{stray['index']} exited {stray['observed_rc']}, expected "
            f"{stray['expected_rc']}. The run is INVALID and is not classified.")

    def detail(self) -> dict[str, object]:
        return dict(self.stray)


class IdentityContractBreach(ExecutionContractBreach):
    """An arm's bytes moved, or vanished, after the freeze."""

    kind = "identity-contract"

    def __init__(self, when: str, role: str, expected: str, observed: str,
                 why: str) -> None:
        self.when, self.role = when, role
        self.expected, self.observed = expected, observed
        super().__init__(f"{when}: arm {role} — {why}")

    def detail(self) -> dict[str, object]:
        return {"when": self.when, "arm": self.role,
                "expected_sha256": self.expected, "observed_sha256": self.observed}


# --- P0: a timed process must have done the work its arm exists to do --------

# Arm A and B are the Round 6 helper: argc >= 2 and a finished loop exits 0.
# Arm C is `own-cli ownir` with no document, which is the instrument's own
# `core-usage` floor and exits 2.
EXPECTED_RC = {"A": 0, "B": 0, "C": 2}


# --- P1: the work is the Round 6 2 ms rung, by binding rather than by memory --


@dataclass(frozen=True)
class WorkBinding:
    iterations: int
    helper_sha256: str
    achieved_median_ms: float
    source: str

    def as_dict(self) -> dict[str, object]:
        return {"iterations": self.iterations, "helper_sha256": self.helper_sha256,
                "round6_achieved_median_ms": self.achieved_median_ms,
                "source": self.source, "target_rung_ms": TARGET_RUNG_MS}


def bind_work(scales: Path = SCALES) -> WorkBinding:
    """Read the iteration count off Round 6's committed ladder.

    The draft said "the Round 6 helper at its 2 ms rung" and left the number in
    prose. A runner that re-derived it would be calibrating a new work count
    after authorisation, which is a knob; a runner that hard-coded it would be a
    number nobody could trace. It is read from the artifact that established it.
    """
    doc = json.loads(scales.read_text(encoding="utf-8"))
    rung = next((r for r in doc["rungs"] if r.get("target_ms") == TARGET_RUNG_MS), None)
    if rung is None:
        raise ExecutionContractBreach(
            f"{scales.name} has no {TARGET_RUNG_MS} ms rung; the arms' work is "
            "undefined and the round cannot start")
    if not rung.get("iterations"):
        raise ExecutionContractBreach(
            f"the {TARGET_RUNG_MS} ms rung records {rung.get('iterations')!r} iterations")
    return WorkBinding(int(rung["iterations"]), str(doc["helper_sha256"]),
                       float(rung["achieved_median_ms"]), pf._rel(scales))


# --- P0-1: the preflighted bytes are the timed bytes -------------------------


@dataclass(frozen=True)
class ArmIdentity:
    role: str
    path: Path
    sha256: str
    bytes_: int

    def as_dict(self) -> dict[str, object]:
        return {"role": self.role, "name": pf._rel(self.path),
                "sha256": self.sha256, "file_bytes": self.bytes_}


def _identity(role: str, path: Path) -> ArmIdentity:
    data = path.read_bytes()
    return ArmIdentity(role, path, hashlib.sha256(data).hexdigest(), len(data))


def verify_identities(frozen: dict[str, ArmIdentity], when: str) -> None:
    """Re-hash every arm and refuse if any byte moved. Outside every clock.

    Called before each block and after the last one. Cheap, and the alternative
    is discovering mid-dataset that something rebuilt an arm underneath the
    round.
    """
    for role, want in frozen.items():
        if not want.path.is_file():
            raise IdentityContractBreach(
                when, role, want.sha256, "",
                f"{want.path.name} no longer exists; the bytes that passed B1-B4 are "
                "gone and nothing may be timed against them")
        got = _identity(role, want.path)
        if got.sha256 != want.sha256 or got.bytes_ != want.bytes_:
            raise IdentityContractBreach(
                when, role, want.sha256, got.sha256,
                f"changed since the freeze — {want.sha256[:12]} ({want.bytes_} bytes) "
                f"became {got.sha256[:12]} ({got.bytes_} bytes). The preflight proved "
                "properties of bytes that are no longer here.")


@dataclass(frozen=True)
class Prepared:
    """Everything settled before the clock, typed rather than a bag of objects."""

    binding: WorkBinding
    build: dict[str, object]
    checks: dict[str, dict[str, object]]
    preflight_failed: list[str]
    frozen: dict[str, ArmIdentity]
    binding_ok: bool
    binding_problem: str
    arm_c_mapped_bytes: int
    outcome: OutcomePreflight

    @property
    def stop_conditions(self) -> list[str]:
        stop = []
        if self.preflight_failed:
            stop.append(f"B1-B4 failed: {self.preflight_failed}")
        if not self.binding_ok:
            stop.append(self.binding_problem)
        if not self.outcome.all_passed:
            stop.append("the untimed outcome preflight refused arm(s) "
                        + ", ".join(self.outcome.failed) + ": "
                        + "; ".join(f"arm {a} {self.outcome.arms[a].why}"
                                    for a in self.outcome.failed))
        return stop


def check_binding(arm_a_sha256: str, binding: WorkBinding) -> tuple[bool, str]:
    """Arm A must BE the Round 6 helper, by sha256, or the round stops.

    Separated from `prepare` so a control can exercise BOTH directions. A check
    only ever shown matching input is a check nobody has tested, and this one
    guards the difference between "460280 iterations means 2 ms" and "460280
    iterations means whatever this other binary happens to do".

    The refusal is deliberately terminal. Re-deriving an iteration count that
    lands near 2 ms would be calibrating a new knob after authorisation, which
    is the move the whole round forbids.
    """
    if arm_a_sha256 == binding.helper_sha256:
        return True, ""
    return False, (
        f"arm A hashes {arm_a_sha256[:12]} but Round 6's helper is "
        f"{binding.helper_sha256[:12]}: the arms are not the ladder's helper, so "
        f"{binding.iterations} iterations no longer means {TARGET_RUNG_MS} ms here. "
        "STOP — do not re-derive an iteration count after authorisation.")


def _argv_for(role: str, frozen: dict[str, ArmIdentity], binding: WorkBinding
              ) -> list[str]:
    """One definition of how each arm is invoked, shared by preflight and timing.

    Two copies would be two experiments: the untimed probe would verify one
    command line and the clock would measure another.
    """
    if role == "C":
        return [str(frozen["C"].path), "ownir"]
    return [str(frozen[role].path), str(binding.iterations)]


def measurement_env() -> dict[str, str]:
    import os

    import perf_baseline as pb
    env = dict(os.environ)
    for uncontrolled in pb.REFERENCE_ENV_PINNED_UNSET:
        env.pop(uncontrolled, None)
    return env


@dataclass(frozen=True)
class ArmOutcome:
    """One arm's untimed proof that it does the work it exists to do."""

    role: str
    passed: bool
    expected_rc: int
    observed_rc: int
    contract: str
    why: str
    detail: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {"role": self.role, "pass": self.passed, "expected_rc": self.expected_rc,
                "observed_rc": self.observed_rc, "contract": self.contract,
                "why": self.why, **self.detail}


@dataclass(frozen=True)
class OutcomePreflight:
    arms: dict[str, ArmOutcome]
    ran: bool

    @property
    def failed(self) -> list[str]:
        return sorted(r for r, a in self.arms.items() if not a.passed)

    @property
    def all_passed(self) -> bool:
        return not self.failed

    def as_dict(self) -> dict[str, object]:
        return {"ran": self.ran, "all_passed": self.all_passed, "failed": self.failed,
                "arms": {r: a.as_dict() for r, a in self.arms.items()},
                "note": ("untimed; no clock was started for any of these probes"
                         if self.ran else
                         "not run: the arms did not pass B1-B4 or the work binding")}


def outcome_preflight(frozen: dict[str, ArmIdentity], binding: WorkBinding
                      ) -> OutcomePreflight:
    """Prove each arm does its job BEFORE anything is timed. No clock here.

    Arm C is verified through the instrument's own `core-usage` rung — the same
    `expect_rc` and the same `usage-help` evidence contract the frozen harness
    applies, not a third restatement of it. Exit 2 alone is not enough: a
    different failure can exit 2 too, which is why that contract also requires
    stdout to name the subcommand and stderr to be empty.

    Arms A and B are the Round 6 helper and produce no output; their ratified
    contract is the exit code. Their stream lengths are recorded as observations
    rather than promoted to stop conditions.
    """
    import subprocess

    import perf_baseline as pb

    env = measurement_env()
    arms: dict[str, ArmOutcome] = {}

    for role in ("A", "B"):
        r = subprocess.run(_argv_for(role, frozen, binding), capture_output=True,
                           cwd=str(ROOT), env=env)
        passed = r.returncode == EXPECTED_RC[role]
        arms[role] = ArmOutcome(
            role=role, passed=passed, expected_rc=EXPECTED_RC[role],
            observed_rc=r.returncode,
            contract="exit code only; the helper writes nothing by construction",
            why=(f"ran {binding.iterations} iterations and exited {r.returncode}"
                 if passed else
                 f"exited {r.returncode}, not {EXPECTED_RC[role]}: it did not do the "
                 "work, and timing it would measure the wrong path"),
            detail={"stdout_bytes": len(r.stdout), "stderr_bytes": len(r.stderr)})

    rung = next(x for x in pb.RUNGS if x.id == "core-usage")
    outcome = _harness_for(frozen["C"].path).verify_outcome(
        rung, _argv_for("C", frozen, binding), env, ROOT)
    valid = bool(outcome["valid"])
    arms["C"] = ArmOutcome(
        role="C", passed=valid, expected_rc=EXPECTED_RC["C"],
        observed_rc=int(str(outcome["observed_exit_code"])),
        contract=f"perf_baseline rung {rung.id!r}: expect_rc {sorted(rung.expect_rc)}, "
                 f"evidence {rung.evidence!r}",
        why=(f"satisfied the instrument's own {rung.id} contract" if valid else
             f"did not do the {rung.id} work: {outcome['problems']}"),
        detail={"problems": outcome["problems"]})

    return OutcomePreflight(arms=arms, ran=True)


def _harness_for(candidate: Path) -> pb.Harness:
    """A harness instance, built only to reuse the frozen outcome verifier.

    Constructing it starts nothing: `verify_outcome` runs one untimed
    subprocess and reads its streams.
    """
    import perf_baseline as pb
    return pb.Harness(gate=pb.IdentityGate.load(pb.load_manifest()[1]),
                      session=pb.SessionIdentity.freeze(candidate), rss=pb.RssProbe(),
                      tmp=candidate.parent, candidate=candidate,
                      warmup_discards=WARMUP_DISCARDS, repetitions=0, seed=0)


def prepare(candidate: Path, build_dir: Path) -> Prepared:
    """Bind, build once, preflight THOSE files, freeze their identities.

    Everything up to the clock, and nothing that starts one.
    """
    binding = bind_work()
    arm_c = Elf64(candidate)
    built = pf.build_arms(build_dir, arm_c.mapped_bytes)
    arm_a_path = Path(str(built["arm_a"]))
    arm_b_path = Path(str(built["arm_b"]))
    arm_a, arm_b = Elf64(arm_a_path), Elf64(arm_b_path)

    checks = {"B1": pf.check_b1(arm_b), "B2": pf.check_b2(arm_b),
              "B3": pf.check_b3(arm_b, arm_c), "B4": pf.check_b4(arm_a, arm_b)}
    failed = sorted(k for k, v in checks.items() if not v["pass"])

    frozen = {"A": _identity("A", arm_a_path), "B": _identity("B", arm_b_path),
              "C": _identity("C", candidate)}

    binding_ok, binding_problem = check_binding(frozen["A"].sha256, binding)

    # The outcome preflight runs only once the arms are the arms: verifying a
    # binary that failed its binding check would answer a question nobody asked.
    outcome = (outcome_preflight(frozen, binding) if binding_ok and not failed
               else OutcomePreflight(arms={}, ran=False))

    return Prepared(binding=binding, build=built, checks=checks, preflight_failed=failed,
                    frozen=frozen, binding_ok=binding_ok, binding_problem=binding_problem,
                    arm_c_mapped_bytes=arm_c.mapped_bytes, outcome=outcome)


# --- the clock, reachable from exactly one place -----------------------------


def time_half(harness: object, half: sch.Half, argv: list[str], env: dict[str, str],
              cwd: Path, repetitions: int, discards: int) -> dict[str, object]:
    """The ONLY function in this round that starts a clock.

    Routed through the instrument's own `Harness._run_once`, so the measured
    interval is the instrument's and not a re-implementation that happens to
    look similar. Plan mode never reaches this function, and a control counts
    the calls rather than taking that on faith.

    EVERY spawn is checked against its arm's exit code, warmup discards
    included. Calling `_run_once` directly is what let this round skip the
    instrument's own outcome layer — the layer that exists because twelve cells
    once timed `command-not-found` accurately, reproducibly, and to no purpose.
    A discarded iteration that failed is still evidence the process is broken,
    so it is checked even though its numbers are thrown away.

    Only the exit code is read here. Capturing stdout inside a measured interval
    would change what the interval measures, which is exactly why the rich
    output contract runs once, untimed, in `outcome_preflight`.
    """
    run_once = harness._run_once                       # type: ignore[attr-defined]
    expected = EXPECTED_RC[half.arm]

    def _check(row: dict[str, object], spawn_kind: str, index: int) -> dict[str, object]:
        if int(row["rc"]) != expected:                  # type: ignore[call-overload]
            # Immediately. Finishing the half after a known breach would spawn
            # more processes to produce numbers nobody is allowed to use.
            raise OutcomeContractBreach(
                {"block": f"{half.regime}|n{half.n}|s{half.session}", "arm": half.arm,
                 "half": half.half, "spawn_kind": spawn_kind, "index": index,
                 "observed_rc": row["rc"], "expected_rc": expected})
        return row

    for i in range(discards):
        _check(run_once(argv, env, cwd), "warmup", i)
    samples = [_check(run_once(argv, env, cwd), "sample", i) for i in range(repetitions)]
    return {"half": half.key, "expected_rc": expected, "samples": samples}


# --- the pass ----------------------------------------------------------------


def _invalid(base: dict[str, object], exc: ExecutionContractBreach) -> dict[str, object]:
    """Turn a refusal into a durable record. The black box, not just the crash.

    An exception that escapes to a traceback proves the runner refused and
    leaves nothing behind to say so: no file, no abort, nothing to investigate
    at 3am. That is the same shape as a control that dies before reporting,
    which this project keeps rediscovering — here with the measurement runner
    itself playing the part.
    """
    return {**base, "run_valid": False, "measurements": None,
            "abort": {"kind": exc.kind, "reason": str(exc), **exc.detail()},
            "verdict": f"INVALID / STOP ({exc.kind}): {exc}"}


def run(candidate: Path, build_dir: Path, measure: bool) -> dict[str, object]:
    base: dict[str, object] = {
        "tag": TAG, "mode": "measure" if measure else "plan",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        prepared = prepare(candidate, build_dir)
    except ExecutionContractBreach as exc:
        # Even a breach before the arms exist leaves a record.
        return _invalid(base, exc)
    plan = sch.plan()
    spawns = sch.process_spawns(warmup_discards=WARMUP_DISCARDS)

    stop = prepared.stop_conditions

    record: dict[str, object] = {
        **base,
        "work_binding": prepared.binding.as_dict(),
        "preflight": {"checks": prepared.checks, "failed": prepared.preflight_failed},
        "outcome_preflight": prepared.outcome.as_dict(),
        "frozen_arms": {r: i.as_dict() for r, i in prepared.frozen.items()},
        "schedule": plan,
        "planned_process_spawns": spawns,
        "stop_conditions": stop,
    }

    if stop:
        record["verdict"] = "STOP: " + "; ".join(stop)
        record["measurements"] = None
        record["run_valid"] = False
        return record

    if not measure:
        # The return is the enforcement. Plan mode does not step over a timing
        # loop guarded by a flag — it never reaches one.
        record["verdict"] = (
            "PLAN ONLY. Arms built, B1-B4 passed on these exact bytes, identities "
            "frozen, execution order fixed. No clock was started and none is "
            "authorised: the calibration pass is a separate decision.")
        record["measurements"] = None
        record["run_valid"] = True
        return record

    # The one boundary. Whichever contract breaks — a stray exit code, an arm
    # whose bytes moved — the run ends INVALID and says so in a file.
    partial: list[dict[str, object]] = []
    order: list[str] = []
    try:
        record.update(_measure(prepared, candidate, partial, order))
        record["run_valid"] = True
    except ExecutionContractBreach as exc:
        record = _invalid(record, exc)
        record["partial_measurements"] = {
            "not_evidence": True,
            "why_not_evidence": "the run was refused before it finished; these halves "
                                "are kept for investigation and must never be read as "
                                "data, classified, or compared against anything",
            "halves_completed": len(partial),
            "actual_order": order,
            "halves": partial,
        }
    return record


def _measure(prepared: Prepared, candidate: Path, results: list[dict[str, object]],
             actual_order: list[str]) -> dict[str, object]:
    """The timing pass. Identity is re-verified before every block and after the last."""
    import perf_baseline as pb

    frozen = prepared.frozen

    harness = pb.Harness(
        gate=pb.IdentityGate.load(pb.load_manifest()[1]),
        session=pb.SessionIdentity.freeze(candidate), rss=pb.RssProbe(),
        tmp=Path(str(prepared.build["arm_a"])).parent,
        candidate=candidate, warmup_discards=WARMUP_DISCARDS, repetitions=0, seed=0)

    # The SAME argv the untimed preflight verified. Two definitions would mean
    # the probe checked one command line and the clock measured another.
    argv_for = {r: _argv_for(r, frozen, prepared.binding) for r in ("A", "B", "C")}
    env = measurement_env()

    for block in sch.blocks():
        verify_identities(frozen, f"before block {block.key}")
        discards = WARMUP_DISCARDS if block.regime == "warm" else 0
        for half in block.halves:
            actual_order.append(half.key)
            results.append(time_half(harness, half, argv_for[half.arm], env, ROOT,
                                     block.n, discards))
    verify_identities(frozen, "after the last block")

    return {"measurements": results, "actual_order": actual_order,
            "verdict": f"{len(results)} halves measured in the preregistered order"}


def main() -> int:
    ap = argparse.ArgumentParser(description="Round 7 measurement runner")
    ap.add_argument("--candidate", required=True, type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--build-dir", type=Path, default=Path("round7-arms"))
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", default=True,
                      help="build, preflight, freeze, schedule — and stop (default)")
    mode.add_argument("--measure", action="store_true",
                      help="run the calibration pass; a SEPARATE authorisation")
    args = ap.parse_args()

    record = run(args.candidate.resolve(), args.build_dir, measure=args.measure)
    blob = json.dumps(record, indent=2)
    # Written on every path, refusals included. A runner that only produces a
    # file when it succeeds has no way to tell anyone why it did not.
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(blob + "\n", encoding="utf-8")
        print(f"wrote {args.out}")
        print(record["verdict"])
    else:
        print(blob)
    return 0 if record.get("run_valid") and not record.get("stop_conditions") else 1


if __name__ == "__main__":
    sys.exit(main())
