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

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import preflight as pf
import schedule as sch
from elfread import Elf64

ROOT = Path(__file__).resolve().parent.parent.parent
SCALES = ROOT / "docs/evidence/round6/p022-263a-round6-scales.linux.json"
TARGET_RUNG_MS = 2
WARMUP_DISCARDS = 2          # policy, not a knob: `warm` discards two, cold none
TAG = "CALIBRATION_ONLY"


class ExecutionContractBreach(Exception):
    """The round was asked to measure something it did not preflight."""


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
            raise ExecutionContractBreach(
                f"{when}: arm {role} ({want.path.name}) no longer exists; the bytes "
                "that passed B1-B4 are gone and nothing may be timed against them")
        got = _identity(role, want.path)
        if got.sha256 != want.sha256 or got.bytes_ != want.bytes_:
            raise ExecutionContractBreach(
                f"{when}: arm {role} changed since the freeze — {want.sha256[:12]} "
                f"({want.bytes_} bytes) became {got.sha256[:12]} ({got.bytes_} bytes). "
                "The preflight proved properties of bytes that are no longer here.")


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

    @property
    def stop_conditions(self) -> list[str]:
        stop = []
        if self.preflight_failed:
            stop.append(f"B1-B4 failed: {self.preflight_failed}")
        if not self.binding_ok:
            stop.append(self.binding_problem)
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

    return Prepared(binding=binding, build=built, checks=checks, preflight_failed=failed,
                    frozen=frozen, binding_ok=binding_ok, binding_problem=binding_problem,
                    arm_c_mapped_bytes=arm_c.mapped_bytes)


# --- the clock, reachable from exactly one place -----------------------------


def time_half(harness: object, half: sch.Half, argv: list[str], env: dict[str, str],
              cwd: Path, repetitions: int, discards: int) -> dict[str, object]:
    """The ONLY function in this round that starts a clock.

    Routed through the instrument's own `Harness._run_once`, so the measured
    interval is the instrument's and not a re-implementation that happens to
    look similar. Plan mode never reaches this function, and a control counts
    the calls rather than taking that on faith.
    """
    run_once = harness._run_once                       # type: ignore[attr-defined]
    for _ in range(discards):
        run_once(argv, env, cwd)
    samples = [run_once(argv, env, cwd) for _ in range(repetitions)]
    return {"half": half.key, "samples": samples}


# --- the pass ----------------------------------------------------------------


def run(candidate: Path, build_dir: Path, measure: bool) -> dict[str, object]:
    prepared = prepare(candidate, build_dir)
    plan = sch.plan()
    spawns = sch.process_spawns(warmup_discards=WARMUP_DISCARDS)

    stop = prepared.stop_conditions

    record: dict[str, object] = {
        "tag": TAG,
        "mode": "measure" if measure else "plan",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "work_binding": prepared.binding.as_dict(),
        "preflight": {"checks": prepared.checks, "failed": prepared.preflight_failed},
        "frozen_arms": {r: i.as_dict() for r, i in prepared.frozen.items()},
        "schedule": plan,
        "planned_process_spawns": spawns,
        "stop_conditions": stop,
    }

    if stop:
        record["verdict"] = "STOP: " + "; ".join(stop)
        record["measurements"] = None
        return record

    if not measure:
        # The return is the enforcement. Plan mode does not step over a timing
        # loop guarded by a flag — it never reaches one.
        record["verdict"] = (
            "PLAN ONLY. Arms built, B1-B4 passed on these exact bytes, identities "
            "frozen, execution order fixed. No clock was started and none is "
            "authorised: the calibration pass is a separate decision.")
        record["measurements"] = None
        return record

    record.update(_measure(prepared, candidate))
    return record


def _measure(prepared: Prepared, candidate: Path) -> dict[str, object]:
    """The timing pass. Identity is re-verified before every block and after the last."""
    import perf_baseline as pb

    frozen = prepared.frozen
    iterations = str(prepared.binding.iterations)

    harness = pb.Harness(
        gate=pb.IdentityGate.load(pb.load_manifest()[1]),
        session=pb.SessionIdentity.freeze(candidate), rss=pb.RssProbe(),
        tmp=Path(str(prepared.build["arm_a"])).parent,
        candidate=candidate, warmup_discards=WARMUP_DISCARDS, repetitions=0, seed=0)

    argv_for = {
        "A": [str(frozen["A"].path), iterations],
        "B": [str(frozen["B"].path), iterations],
        "C": [str(frozen["C"].path), "ownir"],
    }
    import os
    env = dict(os.environ)
    for uncontrolled in pb.REFERENCE_ENV_PINNED_UNSET:
        env.pop(uncontrolled, None)

    results, actual_order = [], []
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
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(blob + "\n", encoding="utf-8")
        print(f"wrote {args.out}")
        print(record["verdict"])
    else:
        print(blob)
    return 1 if record["stop_conditions"] else 0


if __name__ == "__main__":
    sys.exit(main())
