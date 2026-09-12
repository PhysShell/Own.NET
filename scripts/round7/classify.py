#!/usr/bin/env python3
"""Round 7's outcome classifier — CALIBRATION_ONLY.

The ONE implementation of the preregistered rules. Nothing else in the round may
restate them: a second copy is a second opinion, and the reading would then be
able to choose. It is pure by construction — numbers in, an outcome out, no
files, no clock, no I/O — so it can be exercised exhaustively before any
measurement exists.

The rules, as ratified by the owner, per regime and per repetition count, where
A, B and C abbreviate D(A), D(B), D(C) — the median across sessions of
|median(second half) - median(first half)| for that arm:

    P4  the witness did not reproduce           C <= 1.5A
    P1  padded-image effect reproduces it       C > 1.5A and B >= 3A
                                                and (2/3)B <= C <= 1.5B
    P2  padding-only effect insufficient        B <= 1.5A and C >= 3A
    P3  padding contributes, not the whole      B >= 3A and C >= 2B
    P5  inconclusive                            anything else

plus the ratified degenerate guard:

    if A == 0 at either repetition count in a regime, that regime is P5.

Why only A, and why exactly zero
--------------------------------
The overlap algebra, done properly, is narrower than the previous draft claimed.
P1 is disjoint from every other rule unconditionally: its `C > 1.5A` clause
excludes P4 outright, and every other intersection forces B = 0 and then C = 0,
which contradicts `C > 1.5A`. The remaining overlaps -- P2 with P3, and those
two with P4 -- all require A = 0 AND B = 0 together. So the guard is not what
makes the set disjoint; `_OVERLAP_FREE_EXCEPT_AT_ZERO_A_AND_B` in the controls
proves that directly.

The guard exists for a metrological reason instead. A is the multiplicative
reference for the whole scheme: 1.5A, 3A and 6A are meaningful only as multiples
of a baseline that has a size. At A = 0 any positive B or C is infinitely larger
than the baseline, and the rules still classify -- definitely, and meaninglessly.

B = 0 has no such property and is NOT a refusal. A = 1, B = 0, C = 4 is a clean
P2: the padded arm shows no excess and the real binary does. Routing that to P5
would discard one of the cleanest results this round can produce.

No epsilon. A tolerance like `A < 0.01 ms` would be an absolute threshold chosen
with no preregistered basis -- the exact thing this round forbids. Exact zero is
a structural degenerate case, not another knob.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction

# The ratified repetition counts. Not a knob: no other value may be measured.
REPETITION_COUNTS = (5, 15)
REGIMES = ("process-cold", "warm")
OUTCOMES = ("P1", "P2", "P3", "P4", "P5")

OUTCOME_NAMES = {
    "P1": "the padded-image effect reproduces the elevation",
    "P2": "the padding-only effect is insufficient, the real binary is elevated",
    "P3": "padding contributes but does not explain the whole",
    "P4": "the witness did not reproduce",
    "P5": "inconclusive",
}


class ClassifierError(Exception):
    """The classifier was handed something it must not silently classify."""


class AmbiguousOutcome(ClassifierError):
    """More than one rule fired on one triple.

    Unreachable through `regime_outcome`, because the only triples where the
    ratified rules overlap have A = 0 and the zero-A guard routes those to P5
    first. It is raised rather than resolved by precedence: a classifier that
    quietly picked the first matching rule would hide exactly the defect that
    made the previous draft's table unreadable.
    """


def _ratio(x: float) -> Fraction:
    """Exact arithmetic for the comparisons, so 2/3 is 2/3 and not 0.6666...

    The boundaries are ratios of measured quantities, and a binary-float 2/3
    would decide the `(2/3)B <= C` edge by rounding direction rather than by the
    preregistered rule.
    """
    return Fraction(x).limit_denominator(10 ** 12)


def _check(name: str, value: float) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (int, float, Fraction)):
        raise ClassifierError(f"D({name}) is {type(value).__name__}, not a measurement")
    if not math.isfinite(float(value)):
        raise ClassifierError(f"D({name}) is {value!r}; a non-finite drift is not a "
                              "measurement and must not fall through to P5")
    if value < 0:
        raise ClassifierError(f"D({name}) is {value!r}; D is a median of ABSOLUTE "
                              "differences and cannot be negative")
    return _ratio(value)


def rules_fired(a: float, b: float, c: float) -> tuple[str, ...]:
    """Every rule the triple satisfies, in ratified order. Normally exactly one.

    Exposed so a control can count how many fire rather than trust that one
    does. P5 is not among them: it is the absence of the others.
    """
    A, B, C = _check("A", a), _check("B", b), _check("C", c)
    three_halves = Fraction(3, 2)
    fired = []
    if C <= three_halves * A:
        fired.append("P4")
    if C > three_halves * A and B >= 3 * A and Fraction(2, 3) * B <= C <= three_halves * B:
        fired.append("P1")
    if B <= three_halves * A and C >= 3 * A:
        fired.append("P2")
    if B >= 3 * A and C >= 2 * B:
        fired.append("P3")
    return tuple(fired)


def outcome_at(a: float, b: float, c: float) -> str:
    """One repetition count, one regime. P1-P4, or P5 when no rule fires.

    Does NOT apply the zero-A guard: the guard is a property of a regime across
    both repetition counts, and applying it here would hide from the controls
    the very overlaps it exists to step around.
    """
    fired = rules_fired(a, b, c)
    if len(fired) > 1:
        raise AmbiguousOutcome(
            f"A={a!r}, B={b!r}, C={c!r} fires {list(fired)}: the outcome rules are "
            "not mutually exclusive here, and a classifier that chose between them "
            "would be choosing the result")
    return fired[0] if fired else "P5"


@dataclass(frozen=True)
class RegimeOutcome:
    regime: str
    outcome: str
    why: str
    per_count: dict[int, str]


def regime_outcome(regime: str, by_count: dict[int, tuple[float, float, float]]
                   ) -> RegimeOutcome:
    """One regime's verdict from its (A, B, C) triple at each repetition count.

    The three gates, in the ratified order: the zero-A guard, then the rules,
    then agreement between n=5 and n=15.
    """
    if regime not in REGIMES:
        raise ClassifierError(f"{regime!r} is not a preregistered regime {REGIMES}")
    missing = [n for n in REPETITION_COUNTS if n not in by_count]
    extra = [n for n in by_count if n not in REPETITION_COUNTS]
    if missing or extra:
        raise ClassifierError(
            f"{regime}: repetition counts must be exactly {list(REPETITION_COUNTS)} "
            f"(missing {missing}, unexpected {extra}); no other count may be measured")

    # (1) The zero-A guard. Exact zero, either count, either regime-half.
    zeroed = [n for n in REPETITION_COUNTS if _check("A", by_count[n][0]) == 0]
    if zeroed:
        return RegimeOutcome(regime, "P5", per_count={},
                             why=f"D(A) is exactly 0 at n={zeroed}: A is the "
                                 "multiplicative reference for 1.5A, 3A and 6A, and "
                                 "against a baseline of zero any positive drift is "
                                 "infinitely large. Definite, and metrologically "
                                 "degenerate.")

    # (2) The rules, independently at each count.
    per_count = {n: outcome_at(*by_count[n]) for n in REPETITION_COUNTS}

    # (3) Agreement WITHIN the regime. Disagreement BETWEEN regimes is not P5 —
    #     it is a cache- and state-sensitivity signal, and the caller reports it.
    distinct = set(per_count.values())
    if len(distinct) > 1:
        return RegimeOutcome(regime, "P5", per_count=per_count,
                             why=f"n=5 classified {per_count[5]} and n=15 classified "
                                 f"{per_count[15]}; a rule must hold at both counts "
                                 "within a regime to fire")
    only = per_count[REPETITION_COUNTS[0]]
    return RegimeOutcome(regime, only, per_count=per_count,
                         why=f"{only} held at n=5 and n=15: {OUTCOME_NAMES[only]}")


def read_round(by_regime: dict[str, dict[int, tuple[float, float, float]]]
               ) -> dict[str, object]:
    """Both regimes, classified independently, plus the cross-regime statement.

    A cold/warm split is reported as a finding about where the phenomenon lives.
    Collapsing it into P5 would throw away the most informative thing this round
    can produce.
    """
    results = {r: regime_outcome(r, by_regime[r]) for r in REGIMES}
    outcomes = {r: results[r].outcome for r in REGIMES}
    split = outcomes["process-cold"] != outcomes["warm"]
    return {
        "per_regime": {r: {"outcome": results[r].outcome, "why": results[r].why,
                           "per_count": results[r].per_count} for r in REGIMES},
        "regime_split": split,
        "regime_split_reading": (
            f"process-cold classified {outcomes['process-cold']} and warm classified "
            f"{outcomes['warm']}. This is a cache- and state-sensitivity signal, NOT "
            "P5: both regimes spawn a fresh process per iteration and differ only in "
            "whether the first two are discarded."
            if split else "both regimes classified the same; no split to report"),
        "tag": "CALIBRATION_ONLY",
    }
