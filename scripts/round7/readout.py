#!/usr/bin/env python3
"""Round 7's reading — CALIBRATION_ONLY, and written before the data existed.

This file computes nothing the preregistration did not already fix. It exists
separately from `runner.py` because the runner produces observations and a
reading interprets them, and because a reading written after seeing numbers is
a reading that can be steered by them. It was authored, tested against synthetic
triples, and its sha256 recorded BEFORE the measurement pass was started; the
committed reading quotes that digest so the claim is checkable rather than
asserted.

What is preregistered, quoted from the ratified design:

    D(arm, n, regime) = the median across the 10 sessions of
                        |median(second half) - median(first half)|

on `elapsed_ns`. The rules that consume those triples live in `classify.py`,
which is the ONE implementation and is not restated here — this module hands it
numbers and prints what comes back.

Mechanism attribution, also preregistered, applied only after an outcome fires
and only to the arm the fired rule names as elevated:

    Δ is second half - first half within a session; each row is the median
    across the ten sessions of |Δ|.

    work        median |Δ(cpu_user + cpu_system)|  >= 0.5 x median |Δ elapsed|
    scheduler   median |Δ elapsed| >= 2 x median |Δ(cpu_user + cpu_system)|
                AND median |Δ(vol + invol ctx switches)| >= 2 x arm A's
    faults      median |Δ(minor + major faults)| >= 2 x arm A's

More than one may fire. None firing is itself reportable.

Nothing here reads `0.35`, derives a threshold, or drops a session.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import classify as cl

ARMS = ("A", "B", "C")
HALVES = ("first", "second")
EXPECTED_RC = {"A": 0, "B": 0, "C": 2}
SESSIONS = 10

# Which arm a fired rule says is elevated. P4 reproduces nothing and P5 fires no
# rule, so neither licenses an attribution — that is the preregistration's "only
# after an outcome fires", not a judgement made once the numbers were visible.
ELEVATED_BY_OUTCOME: dict[str, tuple[str, ...]] = {
    "P1": ("B", "C"),
    "P2": ("C",),
    "P3": ("B", "C"),
    "P4": (),
    "P5": (),
}

ACCOUNTING_SUMS = {
    "cpu_ns": ("cpu_user_ns", "cpu_system_ns"),
    "context_switches": ("voluntary_context_switches", "involuntary_context_switches"),
    "faults": ("minor_faults", "major_faults"),
}


class ReadoutRefused(Exception):
    """The reading was handed something it must not interpret."""


def _median(values: list[float]) -> float:
    return statistics.median(values)


def _num(row: dict[str, object], field: str, where: str) -> float:
    """One numeric field of one sample, narrowed fail-closed.

    `object` in, `float` out, and a refusal in between for anything that is not
    a number. Coercing here would let a null accounting field -- the shape the
    instrument deliberately produces off POSIX -- become 0.0 and be averaged
    into a median as though it had been measured.
    """
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReadoutRefused(f"{where}: {field} is {value!r}, not a measurement")
    return float(value)


def load_halves(record: dict[str, object]) -> dict[tuple[str, int, int, str, str],
                                                   list[dict[str, object]]]:
    """Index every half by (regime, n, session, arm, half), refusing anything odd.

    Fail-closed on purpose. A reading that quietly skipped a malformed half would
    report a median over whatever survived and call it the preregistered D.
    """
    if record.get("run_valid") is not True:
        raise ReadoutRefused(
            f"run_valid is {record.get('run_valid')!r}; an invalid run is not read. "
            f"abort={record.get('abort')!r}")
    measurements = record.get("measurements")
    if not isinstance(measurements, list):
        raise ReadoutRefused("the record carries no measurements list")

    out: dict[tuple[str, int, int, str, str], list[dict[str, object]]] = {}
    for entry in measurements:
        if not isinstance(entry, dict):
            raise ReadoutRefused(f"a measurement entry is {type(entry).__name__}, not a half")
        key = str(entry.get("half"))
        regime, n_s, s_s, arm, half = key.split("|")
        n, session = int(n_s[1:]), int(s_s[1:])
        samples = entry.get("samples")
        if not isinstance(samples, list) or len(samples) != n:
            count = len(samples) if isinstance(samples, list) else "no"
            raise ReadoutRefused(f"{key}: {count} samples for n={n}")
        rows: list[dict[str, object]] = []
        for i, row in enumerate(samples):
            if not isinstance(row, dict):
                raise ReadoutRefused(f"{key} sample #{i} is {type(row).__name__}, not a row")
            if int(_num(row, "rc", f"{key} sample #{i}")) != EXPECTED_RC[arm]:
                raise ReadoutRefused(
                    f"{key} sample #{i} exited {row['rc']}, expected {EXPECTED_RC[arm]}; "
                    "the runner should already have refused this run")
            rows.append(row)
        out[(regime, n, session, arm, half)] = rows
    return out


def session_deltas(halves: dict[tuple[str, int, int, str, str], list[dict[str, object]]],
                   regime: str, n: int, arm: str, field: str) -> list[float]:
    """|median(second) - median(first)| for each of the ten sessions, in order."""
    deltas = []
    for session in range(1, SESSIONS + 1):
        pair = []
        for half in HALVES:
            key = (regime, n, session, arm, half)
            if key not in halves:
                raise ReadoutRefused(f"missing half {key}; the dataset is incomplete "
                                     "and an incomplete D is not the preregistered D")
            pair.append(_median([_num(r, field, str(key)) for r in halves[key]]))
        deltas.append(abs(pair[1] - pair[0]))
    return deltas


def signed_session_deltas(halves: dict[tuple[str, int, int, str, str], list[dict[str, object]]],
                          regime: str, n: int, arm: str, fields: tuple[str, ...]) -> list[float]:
    """|Δ| per session for a SUM of accounting fields; Δ is second - first."""
    deltas = []
    for session in range(1, SESSIONS + 1):
        pair = []
        for half in HALVES:
            where = f"{regime}|n{n}|s{session}|{arm}|{half}"
            rows = halves[(regime, n, session, arm, half)]
            pair.append(_median([sum(_num(r, f, where) for f in fields) for r in rows]))
        deltas.append(abs(pair[1] - pair[0]))
    return deltas


def drift_table(halves: dict[tuple[str, int, int, str, str], list[dict[str, object]]]
                ) -> dict[str, dict[int, dict[str, object]]]:
    """D(arm, n, regime) on elapsed_ns, with the ten per-session values kept.

    The per-session deltas travel with the median because a median nobody can
    recompute is a number that has to be trusted.
    """
    table: dict[str, dict[int, dict[str, object]]] = {}
    for regime in cl.REGIMES:
        table[regime] = {}
        for n in cl.REPETITION_COUNTS:
            cell: dict[str, object] = {}
            for arm in ARMS:
                d = session_deltas(halves, regime, n, arm, "elapsed_ns")
                cell[arm] = {"D_ns": _median(d), "D_ms": _median(d) / 1e6,
                             "per_session_delta_ns": d}
            table[regime][n] = cell
    return table


def attribution(halves: dict[tuple[str, int, int, str, str], list[dict[str, object]]],
                regime: str, n: int, arm: str) -> dict[str, object]:
    """The preregistered mechanism table for one arm, quoting its arithmetic."""
    elapsed = _median(session_deltas(halves, regime, n, arm, "elapsed_ns"))
    cpu = _median(signed_session_deltas(halves, regime, n, arm, ACCOUNTING_SUMS["cpu_ns"]))
    ctx = _median(signed_session_deltas(halves, regime, n, arm,
                                        ACCOUNTING_SUMS["context_switches"]))
    faults = _median(signed_session_deltas(halves, regime, n, arm, ACCOUNTING_SUMS["faults"]))
    a_ctx = _median(signed_session_deltas(halves, regime, n, "A",
                                          ACCOUNTING_SUMS["context_switches"]))
    a_faults = _median(signed_session_deltas(halves, regime, n, "A", ACCOUNTING_SUMS["faults"]))

    fired = []
    if cpu >= 0.5 * elapsed:
        fired.append("work")
    if elapsed >= 2 * cpu and ctx >= 2 * a_ctx:
        fired.append("scheduler")
    if faults >= 2 * a_faults:
        fired.append("faults")
    return {
        "arm": arm, "n": n,
        "median_abs_delta": {"elapsed_ns": elapsed, "cpu_ns": cpu,
                             "context_switches": ctx, "faults": faults},
        "arm_a_reference": {"context_switches": a_ctx, "faults": a_faults},
        "fired": fired,
        "reading": ("none of the three fired: the drift is visible in wall time and in "
                    "none of the accounting the kernel offers"
                    if not fired else "fired: " + ", ".join(fired)),
    }


def read(record: dict[str, object]) -> dict[str, object]:
    halves = load_halves(record)
    drift = drift_table(halves)

    # Assembled explicitly rather than by comprehension: a drift table missing a
    # regime or a repetition count must refuse by name, not escape as a KeyError.
    # A reading that dies is a traceback; a reading that refuses is a finding.
    by_regime: dict[str, dict[int, tuple[float, float, float]]] = {}
    for regime in cl.REGIMES:
        if regime not in drift:
            raise ReadoutRefused(f"the drift table has no {regime!r} regime")
        by_regime[regime] = {}
        for n in cl.REPETITION_COUNTS:
            if n not in drift[regime]:
                raise ReadoutRefused(
                    f"{regime}: the drift table has no n={n}; a regime is classified "
                    "from both preregistered counts or not at all")
            cell = drift[regime][n]
            by_regime[regime][n] = tuple(  # type: ignore[assignment]
                float(cell[arm]["D_ns"]) for arm in ARMS)  # type: ignore[index]
    outcome = cl.read_round(by_regime)

    attributions: dict[str, object] = {}
    for regime in cl.REGIMES:
        fired = str(outcome["per_regime"][regime]["outcome"])   # type: ignore[index]
        arms = ELEVATED_BY_OUTCOME[fired]
        if not arms:
            attributions[regime] = {
                "applied": False,
                "why": f"{regime} classified {fired}; the preregistration applies the "
                       "mechanism table only after an outcome fires and only to the arm "
                       "that rule names as elevated",
            }
            continue
        attributions[regime] = {
            "applied": True, "elevated_arms": list(arms),
            "rows": [attribution(halves, regime, n, arm)
                     for arm in arms for n in cl.REPETITION_COUNTS],
        }

    return {
        "tag": "CALIBRATION_ONLY",
        "readout_of": "docs/evidence/round7/p022-263a-round7-dataset.linux.json",
        "D_definition": ("D(arm, n, regime) = median across the 10 sessions of "
                         "|median(second half) - median(first half)| on elapsed_ns"),
        "drift": drift,
        "outcome": outcome,
        "mechanism_attribution": attributions,
        "not_derived": ("no threshold, budget, floor or envelope is derived from any "
                        "number here; 0.35 is not consulted, reported or compared "
                        "against; no session was dropped and no run was repeated"),
    }


def _selftest() -> int:
    """Synthetic triples with known answers. Run BEFORE any real data existed."""
    problems = []

    def fake(by_regime: dict[str, dict[int, tuple[float, float, float]]],
             ) -> dict[str, object]:
        ms: list[dict[str, object]] = []
        for regime, by_n in by_regime.items():
            for n, (a, b, c) in by_n.items():
                for arm, d in zip(ARMS, (a, b, c), strict=True):
                    for session in range(1, SESSIONS + 1):
                        for half in HALVES:
                            base = 1_000_000.0
                            val = base + (d if half == "second" else 0.0)
                            ms.append({
                                "half": f"{regime}|n{n}|s{session}|{arm}|{half}",
                                "samples": [
                                    {"elapsed_ns": val, "rc": EXPECTED_RC[arm],
                                     "cpu_user_ns": 0, "cpu_system_ns": 0,
                                     "minor_faults": 0, "major_faults": 0,
                                     "voluntary_context_switches": 0,
                                     "involuntary_context_switches": 0}
                                    for _ in range(n)],
                            })
        return {"run_valid": True, "measurements": ms}

    # Each case: (A, B, C) at both counts in both regimes -> the rule that must fire.
    cases = [
        ((1.0, 3.0, 6.0), "P3"),      # B >= 3A and C >= 2B (C=4 would be P1)
        ((1.0, 1.0, 4.0), "P2"),      # B <= 1.5A and C >= 3A
        ((1.0, 3.0, 3.0), "P1"),      # C > 1.5A, B >= 3A, (2/3)B <= C <= 1.5B
        ((1.0, 3.0, 1.4), "P4"),      # C <= 1.5A
        ((0.0, 3.0, 4.0), "P5"),      # the zero-A guard
        ((1.0, 2.0, 2.0), "P5"),      # no rule fires
    ]
    for triple, want in cases:
        by_regime = {r: dict.fromkeys(cl.REPETITION_COUNTS, triple)
                     for r in cl.REGIMES}
        got = read(fake(by_regime))
        for regime in cl.REGIMES:
            actual = got["outcome"]["per_regime"][regime]["outcome"]  # type: ignore[index]
            if actual != want:
                problems.append(f"{triple} in {regime}: got {actual}, want {want}")
        applied = got["mechanism_attribution"][cl.REGIMES[0]]["applied"]  # type: ignore[index]
        if applied != bool(ELEVATED_BY_OUTCOME[want]):
            problems.append(f"{triple}: attribution applied={applied} for {want}")

    # A regime that disagrees across counts is P5, and a cold/warm split is reported.
    by_regime = {"process-cold": {5: (1.0, 3.0, 4.0), 15: (1.0, 1.0, 4.0)},
                 "warm": {5: (1.0, 1.0, 4.0), 15: (1.0, 1.0, 4.0)}}
    got = read(fake(by_regime))
    if got["outcome"]["per_regime"]["process-cold"]["outcome"] != "P5":   # type: ignore[index]
        problems.append("disagreement across n did not become P5")
    if got["outcome"]["per_regime"]["warm"]["outcome"] != "P2":           # type: ignore[index]
        problems.append("warm should have classified P2")
    if not got["outcome"]["regime_split"]:                                # type: ignore[index]
        problems.append("a cold/warm split was not reported")

    # An invalid run is refused rather than read.
    try:
        read({"run_valid": False, "measurements": None, "abort": {"kind": "x"}})
    except ReadoutRefused:
        pass
    else:
        problems.append("an invalid run was read instead of refused")

    # A stray rc is refused even if the runner somehow let it through.
    bad = fake({r: dict.fromkeys(cl.REPETITION_COUNTS, (1.0, 3.0, 4.0))
                for r in cl.REGIMES})
    bad["measurements"][0]["samples"][0]["rc"] = 127          # type: ignore[index]
    try:
        read(bad)
    except ReadoutRefused:
        pass
    else:
        problems.append("a stray exit code was read instead of refused")

    # A missing half is refused, not silently averaged over what survived.
    short = fake({r: dict.fromkeys(cl.REPETITION_COUNTS, (1.0, 3.0, 4.0))
                  for r in cl.REGIMES})
    trimmed = list(short["measurements"])                     # type: ignore[call-overload]
    trimmed.pop()
    short["measurements"] = trimmed
    try:
        read(short)
    except ReadoutRefused:
        pass
    else:
        problems.append("an incomplete dataset was read instead of refused")

    for p in problems:
        print(f"FAIL[round7-readout]: {p}")
    if not problems:
        print("ok[round7-readout-selftest]: the preregistered D, the frozen classifier, "
              "the attribution gate, and three fail-closed refusals. The full control, "
              "with five refusals and the reproduction check, is `round7-readout` in "
              "tests/test_round7_apparatus.py")
    return 1 if problems else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Round 7 reading")
    ap.add_argument("--dataset", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if not args.dataset:
        ap.error("--dataset is required unless --selftest")
    record = json.loads(args.dataset.read_text(encoding="utf-8"))
    reading = read(record)
    blob = json.dumps(reading, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(blob + "\n", encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(blob)
    return 0


if __name__ == "__main__":
    sys.exit(main())
