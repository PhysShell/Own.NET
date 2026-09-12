#!/usr/bin/env python3
"""#263-A Round 6 — variance characterisation. CALIBRATION_ONLY.

Preregistered in docs/notes/p022-263a-round6-preregistration.md, which was
committed BEFORE this script produced a single number. Read that first: it fixes
the ladder, the repetition counts, the session count, and — crucially — what
each possible shape of the result licenses. Nothing here decides anything.

This module produces NO verdict, applies NO tolerance, and never consults 0.35.
It touches no decisive workload: the only thing it ever spawns is the synthetic
helper in spin.c.

It measures through ``perf_baseline.Harness._run_once`` on purpose. That is the
instrument's own timed interval — perf_counter_ns around Popen and wait4, output
to DEVNULL, RSS read from the kernel's per-child rusage. Round 6 exists to
characterise THAT interval, so re-implementing a lookalike here would
characterise a different one and call the resemblance a result.

Usage:
    metrology.py --calibrate --out scales.json
    metrology.py --measure --scales scales.json --out dataset.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import perf_baseline as pb  # noqa: E402

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "spin.c"
TAG = "CALIBRATION_ONLY"

# Preregistered and not adjustable from the command line.
LADDER_MS = (1, 2, 4, 8, 16, 32, 64, 128)
REPETITIONS = (5, 15)
WARMUP = 2
SESSIONS = 5


def build(out_dir: Path) -> tuple[Path, str]:
    """Compile the helper once and return it with its content identity."""
    binary = out_dir / "spin"
    r = subprocess.run(["gcc", "-O2", "-o", str(binary), str(SOURCE)],
                       capture_output=True, check=False)
    if r.returncode != 0:
        raise SystemExit("helper did not compile: " + r.stderr.decode("utf-8", "replace"))
    digest, _ = pb.sha256_file(binary)
    return binary, digest


def _harness(tmp: Path, binary: Path) -> pb.Harness:
    """A real Harness, so the timed interval is the instrument's own.

    The firewall is never consulted because no workload is ever passed to it —
    ``_run_once`` takes argv directly. No decisive workload exists anywhere in
    this module.
    """
    _, digest = pb.load_manifest()
    return pb.Harness(gate=pb.IdentityGate.load(digest), session=pb.SessionIdentity.freeze(binary),
                      rss=pb.RssProbe(), tmp=tmp, candidate=binary,
                      warmup_discards=WARMUP, repetitions=1, seed=1)


def _series(h: pb.Harness, binary: Path, iterations: int, reps: int) -> list[int]:
    """warmup discards, then `reps` timed fresh-process runs. Raw ns, unsummarised."""
    env = dict(os.environ)
    argv = [str(binary), str(iterations)]
    for _ in range(WARMUP):
        h._run_once(argv, env, ROOT)
    out = []
    for _ in range(reps):
        r = h._run_once(argv, env, ROOT)
        if r["rc"] != 0:
            raise SystemExit(f"helper exited {r['rc']}; the ladder is not measuring what it thinks")
        out.append(int(r["elapsed_ns"]))  # type: ignore[arg-type]
    return out


def _spread(xs: list[int]) -> dict[str, float]:
    """Dispersion, reported and never compared to anything."""
    med = statistics.median(xs)
    q1, q3 = (statistics.quantiles(xs, n=4)[0], statistics.quantiles(xs, n=4)[2]) \
        if len(xs) >= 4 else (min(xs), max(xs))
    return {
        "median_ns": med,
        "mad_ns": statistics.median([abs(x - med) for x in xs]),
        "iqr_ns": q3 - q1,
        "min_ns": min(xs),
        "max_ns": max(xs),
        "n": len(xs),
    }


def _scheduler_signal() -> dict[str, object]:
    """What the machine was doing. A signal, not a control."""
    sig: dict[str, object] = {
        "cpu_affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else [],
        "cpu_count": os.cpu_count(),
    }
    try:
        sig["loadavg"] = os.getloadavg()
    except OSError:
        sig["loadavg"] = None
    try:
        status = Path("/proc/self/status").read_text(encoding="utf-8")
        for line in status.splitlines():
            if line.startswith(("voluntary_ctxt_switches", "nonvoluntary_ctxt_switches")):
                k, v = line.split(":")
                sig[k.strip()] = int(v.strip())
    except OSError:
        pass
    try:
        for line in Path("/proc/stat").read_text(encoding="utf-8").splitlines():
            if line.startswith("ctxt "):
                sig["system_ctxt"] = int(line.split()[1])
    except OSError:
        pass
    return sig


def calibrate(out: Path) -> int:
    """Setup pass: fix an iteration count per rung, once, and record it.

    A helper that re-derives its own duration each run is measuring a moving
    target, so these counts are chosen here and then never touched again.
    """
    with tempfile.TemporaryDirectory(prefix="r6-cal-") as td:
        tmp = Path(td)
        binary, digest = build(tmp)
        h = _harness(tmp, binary)
        floor = statistics.median(_series(h, binary, 0, 9)) / 1e6
        big = statistics.median(_series(h, binary, 10_000_000, 5)) / 1e6
        per_ms = 10_000_000 / max(big - floor, 1e-9)

        rungs = []
        for target in LADDER_MS:
            want = target - floor
            iters = max(0, round(want * per_ms))
            achieved = statistics.median(_series(h, binary, iters, 9)) / 1e6
            rungs.append({
                "target_ms": target, "iterations": iters,
                "achieved_median_ms": round(achieved, 4),
                "at_or_below_spawn_floor": want <= 0,
            })
            print(f"  {target:>4} ms target -> {iters:>10} iterations -> "
                  f"{achieved:7.3f} ms achieved"
                  + ("   [AT/BELOW SPAWN FLOOR]" if want <= 0 else ""))

    payload = {
        "schema": 1, "tag": TAG, "kind": "own.net/p022/round6-scales",
        "not_decision_evidence": "Setup pass. Fixes the helper's work per rung. No verdict, no "
                                 "tolerance, no threshold.",
        "helper_sha256": digest, "helper_source": str(SOURCE.relative_to(ROOT)),
        "spawn_floor_ms": round(floor, 4), "iterations_per_ms": round(per_ms, 1),
        "warmup_discards": WARMUP, "rungs": rungs,
        "scheduler": _scheduler_signal(),
        "platform": platform.platform(), "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                                       time.gmtime()),
    }
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"spawn floor {floor:.3f} ms; helper {digest[:12]}; wrote {out}")
    return 0


def measure(scales: Path, out: Path) -> int:
    """Measurement pass: the preregistered ladder, five A/B sessions per cell."""
    plan = json.loads(scales.read_text(encoding="utf-8"))
    cells = []
    with tempfile.TemporaryDirectory(prefix="r6-run-") as td:
        tmp = Path(td)
        binary, digest = build(tmp)
        if digest != plan["helper_sha256"]:
            raise SystemExit("the helper is not the one the setup pass calibrated")
        h = _harness(tmp, binary)
        for rung in plan["rungs"]:
            for reps in REPETITIONS:
                for session in range(SESSIONS):
                    before = _scheduler_signal()
                    a = _series(h, binary, rung["iterations"], reps)
                    b = _series(h, binary, rung["iterations"], reps)
                    after = _scheduler_signal()
                    sa, sb = _spread(a), _spread(b)
                    delta = abs(sb["median_ns"] - sa["median_ns"])
                    cells.append({
                        "target_ms": rung["target_ms"], "iterations": rung["iterations"],
                        "repetitions": reps, "session": session,
                        "a": sa, "b": sb,
                        "raw_a_ns": a, "raw_b_ns": b,
                        "absolute_median_shift_ns": delta,
                        "relative_median_shift": (delta / sa["median_ns"]
                                                  if sa["median_ns"] else None),
                        "scheduler_before": before, "scheduler_after": after,
                    })
                print(f"  {rung['target_ms']:>4} ms, n={reps:<3} "
                      f"{SESSIONS} sessions done")
    payload = {
        "schema": 1, "tag": TAG, "kind": "own.net/p022/round6-metrology",
        "not_decision_evidence": "Variance characterisation of the instrument's timed interval. "
                                 "NO pass/fail tolerance is computed or applied here, and no "
                                 "value in this file may be used as a D7 threshold.",
        "preregistration": "docs/notes/p022-263a-round6-preregistration.md",
        "helper_sha256": digest, "spawn_floor_ms": plan["spawn_floor_ms"],
        "warmup_discards": WARMUP, "sessions_per_cell": SESSIONS,
        "instrument_harness_digest": pb.harness_digest(),
        "instrument_tree_sha": pb._git_in(ROOT, "rev-parse", "HEAD")[1],
        "platform": platform.platform(),
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cells": cells,
    }
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}: {len(cells)} A/B sessions")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="#263-A Round 6 metrology (CALIBRATION_ONLY)")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--scales", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    if a.calibrate:
        return calibrate(a.out)
    if a.measure:
        if not a.scales:
            raise SystemExit("--measure needs --scales from the setup pass")
        return measure(a.scales, a.out)
    raise SystemExit("choose --calibrate or --measure")


if __name__ == "__main__":
    raise SystemExit(main())
