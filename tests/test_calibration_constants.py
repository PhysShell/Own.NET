#!/usr/bin/env python3
"""#263-A calibration policy — step 5, the ratified design constants.

Step 5 records the five constants the owner chose, bound to the step 4 identity.
It records nothing else. No `A_abs`, no `R_rel`, no selected `N`, no measurement
output: those are empirical, they do not exist yet, and an artifact that made
room for them would be step 7 arriving with step 5's paperwork.

    constants-artifact-shape    the artifact is five design constants and two bindings
    constants-accepted-by-policy the frozen implementation accepts them and round-trips
    constants-bound-to-freeze   the bindings are the step 4 digests, not lookalikes
    constants-no-empirical      no name the policy uses for a fitted quantity appears

`constants-accepted-by-policy` is the one that matters. It does not re-implement
the ranges — `0 < q < 1`, `M > 1`, `G >= 0`, `R_runs >= 2`, a strictly increasing
ladder — because a second copy of those rules would only ever prove the two copies
agree. It hands the committed pairs to the frozen `DesignConstants.from_committed()`
and lets the implementation under freeze be the judge.

Failures print `FAIL[<check>]: <detail>`; nothing stops at the first one.

Run:  python tests/test_calibration_constants.py
"""

from __future__ import annotations

import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "calibration"))

import perf_baseline as pb  # noqa: E402
import policy as pol  # noqa: E402

CONSTANTS_ARTIFACT = ROOT / "docs" / "evidence" / "calibration" / "p022-263a-design-constants.json"
FREEZE_ARTIFACT = ROOT / "docs" / "evidence" / "calibration" / "p022-263a-policy-freeze.json"

ARTIFACT_NAME = "p022-263a-calibration-design-constants"
RATIONALS = ("q", "M", "G")
COUNTS = ("R_runs",)
LADDERS = ("N_ladder",)

_FAILURES: list[tuple[str, str]] = []
_PASSES: list[str] = []


def fail(check: str, detail: str) -> None:
    _FAILURES.append((check, detail))
    print(f"FAIL[{check}]: {detail}")


def ok(check: str, detail: str = "") -> None:
    _PASSES.append(check)
    print(f"ok[{check}]: {detail}" if detail else f"ok[{check}]")


def _exact_int(value: object) -> bool:
    """`bool` is excluded: in Python a bool IS an int, and round 9 was lost to that."""
    return isinstance(value, int) and not isinstance(value, bool)


def _load(path: Path, check: str) -> dict[str, object] | None:
    if not path.exists():
        fail(check, f"{path.relative_to(ROOT).as_posix()} does not exist")
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        fail(check, f"{path.name} could not be read as JSON: {exc}")
        return None
    if not isinstance(loaded, dict):
        fail(check, f"{path.name} is a {type(loaded).__name__}, not an object")
        return None
    return loaded


def control_artifact_shape(art: dict[str, object]) -> None:
    permitted = {"artifact", "bound_measurement_harness_digest",
                 "bound_policy_implementation_digest", "constants", "ratified_by"}
    problems: list[str] = []

    unexpected = sorted(set(art) - permitted)
    missing = sorted(permitted - set(art))
    if unexpected:
        problems.append(f"keys step 5 does not permit: {unexpected}; the empirical "
                        "constants are fitted, not chosen, and have no home here")
    if missing:
        problems.append(f"keys step 5 requires: {missing}")
    if art.get("artifact") != ARTIFACT_NAME:
        problems.append("artifact is not the frozen literal")
    if art.get("ratified_by") != "owner":
        problems.append("ratified_by is not 'owner'; a constant this repository chose "
                        "for itself is the one thing step 5 must never record")
    for key in ("bound_policy_implementation_digest", "bound_measurement_harness_digest"):
        value = art.get(key)
        if not (isinstance(value, str) and len(value) == 64
                and all(ch in "0123456789abcdef" for ch in value)):
            problems.append(f"{key} is not 64 lowercase hex characters")

    constants = art.get("constants")
    if not isinstance(constants, dict):
        problems.append("constants is not an object")
    else:
        expected = set(RATIONALS) | set(COUNTS) | set(LADDERS)
        if set(constants) != expected:
            problems.append(f"constants names {sorted(constants)}, not {sorted(expected)}")
        for name in RATIONALS:
            pair = constants.get(name)
            if not (isinstance(pair, list) and len(pair) == 2 and all(_exact_int(v) for v in pair)):
                problems.append(f"{name} is not a pair of exact integers; a rational is "
                                "committed as a reduced pair, never as a float or a "
                                "decimal string")
        for name in COUNTS:
            if not _exact_int(constants.get(name)):
                problems.append(f"{name} is not an exact integer count")
        for name in LADDERS:
            ladder = constants.get(name)
            if not (isinstance(ladder, list) and ladder and all(_exact_int(v) for v in ladder)):
                problems.append(f"{name} is not a non-empty list of exact integers")

    if problems:
        fail("constants-artifact-shape", "; ".join(problems))
    else:
        ok("constants-artifact-shape",
           f"{len(permitted)} permitted keys and no others; {len(RATIONALS)} rationals as "
           f"reduced pairs, {len(COUNTS)} count and {len(LADDERS)} ladder as exact integers")


def control_accepted_by_policy(art: dict[str, object]) -> None:
    """The frozen implementation is the judge of its own constants."""
    constants = art.get("constants")
    if not isinstance(constants, dict):
        fail("constants-accepted-by-policy", "there are no constants to hand to the policy")
        return
    try:
        built = pol.DesignConstants.from_committed(
            q=tuple(constants["q"]), m=tuple(constants["M"]),      # type: ignore[arg-type]
            r_runs=constants["R_runs"], n_ladder=constants["N_ladder"],  # type: ignore[arg-type]
            g=tuple(constants["G"]))                                # type: ignore[arg-type]
    except (pol.PolicyRefused, KeyError, TypeError, ValueError) as exc:
        fail("constants-accepted-by-policy",
             f"the frozen policy refuses the committed constants: {exc}")
        return

    round_trip = json.loads(json.dumps(built.as_committed()))
    committed = json.loads(json.dumps(constants))
    if round_trip != committed:
        fail("constants-accepted-by-policy",
             f"the policy reads the constants back as {round_trip}, not as the committed "
             f"{committed}; a form that does not survive the round trip is not canonical")
        return
    if not all(isinstance(v, Fraction) for v in (built.q, built.m, built.g)):
        fail("constants-accepted-by-policy", "a rational came back as something other "
                                             "than Fraction")
        return
    ok("constants-accepted-by-policy",
       f"q={built.q}, M={built.m}, R_runs={built.r_runs}, ladder={list(built.n_ladder)} "
       f"stopping at {built.n_ladder[-1]}, G={built.g}; accepted by the frozen "
       "implementation and byte-identical on the round trip")


def control_bound_to_freeze(art: dict[str, object]) -> None:
    freeze = _load(FREEZE_ARTIFACT, "constants-bound-to-freeze")
    if freeze is None:
        return
    problems: list[str] = []
    pairs = (("bound_policy_implementation_digest", "policy_implementation_digest"),
             ("bound_measurement_harness_digest", "measurement_harness_digest"))
    for here, there in pairs:
        if art.get(here) != freeze.get(there):
            problems.append(f"{here} is {str(art.get(here))[:12]} but step 4 froze "
                            f"{str(freeze.get(there))[:12]}")
    live = pb.harness_digest()
    if art.get("bound_measurement_harness_digest") != live:
        problems.append(f"the bound harness digest is not the live one, {live[:12]}")
    if problems:
        fail("constants-bound-to-freeze", "; ".join(problems)
             + "; constants bound to an implementation other than the frozen one are "
               "constants for a policy nobody reviewed")
    else:
        ok("constants-bound-to-freeze",
           f"bound to policy {str(art.get('bound_policy_implementation_digest'))[:12]}… and "
           f"harness {live[:12]}…, both equal to what step 4 froze")


def control_no_empirical(art: dict[str, object]) -> None:
    """No name the policy itself uses for a fitted quantity may appear here.

    The exact schema above is the primary guarantee. This is a second net, and it
    is DERIVED from the module rather than hand-listed: the forbidden names are
    whatever `Envelope` serialises as, so if the policy ever grows another
    empirical field the net grows with it instead of going quietly out of date.

    NO MUTATION ISOLATES THIS CONTROL, and that is recorded rather than papered
    over. Every way of smuggling an empirical name in today is refused one check
    earlier by the exact schema, so the mutation campaign scores those against
    `constants-artifact-shape`. This is defence in depth, which is worth having and
    is not the same thing as tested coverage. Counting it as covered would be the
    defect this PR exists to remove, one level up.
    """
    sample = pol.Envelope(n=1, a_abs=Fraction(0), r_rel=Fraction(0))
    empirical = set(sample.as_committed()) - {"n"}
    empirical |= {"selected_N", "measurements", "elapsed_ns"}

    def names(node: object) -> list[str]:
        if isinstance(node, dict):
            return list(node) + [n for v in node.values() for n in names(v)]
        if isinstance(node, list):
            return [n for item in node for n in names(item)]
        return []

    def floats(node: object) -> list[object]:
        if isinstance(node, dict):
            return [f for v in node.values() for f in floats(v)]
        if isinstance(node, list):
            return [f for item in node for f in floats(item)]
        return [node] if isinstance(node, float) else []

    problems: list[str] = []
    present = sorted(set(names(art)) & empirical)
    if present:
        problems.append(f"names the policy uses for fitted quantities: {present}; those "
                        "are measured, not chosen, and no measurement is authorised")
    stray = floats(art)
    if stray:
        problems.append(f"floating-point values: {stray}; the policy computes in exact "
                        "rationals and a committed decimal is a float to one reader and "
                        "a rational to another")
    if problems:
        fail("constants-no-empirical", "; ".join(problems))
    else:
        ok("constants-no-empirical",
           f"none of {sorted(empirical)} appears, and no value is a float")


def run() -> int:
    art = _load(CONSTANTS_ARTIFACT, "constants-artifact-shape")
    if art is not None:
        control_artifact_shape(art)
        control_accepted_by_policy(art)
        control_bound_to_freeze(art)
        control_no_empirical(art)
    print()
    print(f"calibration constants controls: {len(_PASSES)} passed, {len(_FAILURES)} failed")
    return 1 if _FAILURES else 0


if __name__ == "__main__":
    sys.exit(run())
