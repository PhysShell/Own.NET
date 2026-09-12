#!/usr/bin/env python3
"""#263-A calibration reproducibility policy — the pure implementation.

This module is step 2 of the twelve-step sequence in
`docs/notes/p022-263a-calibration-policy-proposal.md`. It is written **before**
any training corpus exists, because an implementation written with the data
already on disk can be nudged, in a hundred defensible small ways, toward the
answer its author has already seen.

It carries **no constant values and no defaults**. Every design constant is a
required field of one immutable `DesignConstants`, and the empirical constants
are required inputs to the verdict. The code physically cannot hold a number
nobody ratified.

It is pure: no clock, no files, no network, no randomness, no global state. Same
inputs, same outputs, on any platform. All arithmetic is exact rational, because
every boundary in the policy is decided by a comparison and a binary float would
decide some of them by rounding direction instead of by the rule.

What lives here, and what the ratified document says about each:

    canonical representation   §2.6   rationals as reduced pairs; counts as ints
    the four-way verdict       §1     reproducible / not-reproducible /
                                      inconclusive / invalid, cell and pair
    the symmetric comparison   §2.2   bound evaluated at the MIDPOINT
    the per-cell rule          §2.4   inclusive inner, strict outer
    aggregation                §2.5   strict precedence, never a count
    the empirical fit          §3.3   exact vertex enumeration + canonicalisation
    selecting N                §3.4   per-rung envelopes, diminishing returns

Nothing here reads a threshold, consults the incumbent constants, or decides
whether any engine is fast enough. Those are D7 questions and §7 keeps them
behind a different freeze.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from itertools import pairwise
from math import gcd

VERDICTS = ("reproducible", "not-reproducible", "inconclusive", "invalid")


class PolicyRefused(Exception):
    """The policy was handed something it must not silently interpret."""


# --- §2.6 canonical representation -------------------------------------------


def canonical_rational(numerator: object, denominator: object, *, name: str) -> Fraction:
    """One rational quantity, from the reduced integer pair that was committed.

    A float is refused rather than converted. The document exists because a
    committed decimal is a binary float to one implementation and a rational to
    another, and the two then disagree on every boundary case; accepting a float
    here would reintroduce exactly that.
    """
    def _int(label: str, value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise PolicyRefused(
                f"{name}.{label} is {value!r} ({type(value).__name__}); a rational is "
                "committed as a pair of integers, never as a float or a decimal string")
        return value

    num, den = _int("numerator", numerator), _int("denominator", denominator)
    if den <= 0:
        raise PolicyRefused(f"{name} has denominator {den}; the canonical form has a "
                            "strictly positive denominator, so the pair is unique")
    if gcd(abs(num), den) != 1:
        raise PolicyRefused(
            f"{name} is ({num}, {den}), which is not reduced; the canonical form is "
            "unique only when the pair shares no common factor")
    return Fraction(num, den)


def canonical_count(value: object, *, name: str, minimum: int) -> int:
    """One count. A count is an integer, not a rational written as `(n, 1)`.

    Revision 3 required every design constant in reduced-pair form, which left a
    reader deciding whether N = 15 meant the integer or the pair. Counts are
    integers here and rationals are pairs, and nothing has to be guessed.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise PolicyRefused(f"{name} is {value!r} ({type(value).__name__}); a count is "
                            "a canonical integer")
    if value < minimum:
        raise PolicyRefused(f"{name} is {value}; the ratified minimum is {minimum}")
    return int(value)


def exact_rational(value: object, *, name: str) -> Fraction:
    """Every quantity that crosses into the policy's arithmetic, checked at the door.

    `canonical_rational` guards the constants that arrive as committed pairs.
    This guards everything else: measured medians, fitted envelopes, reference
    durations. Without it the exact domain held at exactly one entry point, and
    a float could walk in through a dataclass constructor.

    That is not a typing nicety. `Fraction * float` is a **float** in Python, so
    one float anywhere makes the whole downstream computation floating point:
    the fitted `R_rel`, the bound, the comparison that decides the verdict. A
    module that refused a floating-point LP solver on exactness grounds would
    then be deciding its boundaries by rounding direction anyway.

    A float is **refused, never converted**. `Fraction(0.1)` preserves the binary
    error with impeccable fidelity, which would be funny rather than useful. An
    `int` is refused too: it is exact, but `int / int` is a float in Python, so
    admitting it puts a float one ordinary division away.
    """
    if not isinstance(value, Fraction):
        raise PolicyRefused(
            f"{name} is {value!r} ({type(value).__name__}); this policy computes in "
            "exact rationals and refuses anything else rather than converting it. "
            "Fraction(0.1) would keep the binary error exactly, not remove it")
    return value


def as_pair(value: Fraction) -> tuple[int, int]:
    """The canonical pair for serialisation. Round-trips through `canonical_rational`."""
    return (value.numerator, value.denominator)


def exact_median(values: Sequence[Fraction], *, name: str) -> Fraction:
    """The median in exact arithmetic; an even count averages the two middle values.

    `statistics.median` would return a float for an even-length input and hand a
    rounding decision to the comparison that consumes it.
    """
    if not values:
        raise PolicyRefused(f"{name}: the median of an empty sample is not a number")
    ordered = sorted(exact_rational(v, name=f"{name}[{i}]") for i, v in enumerate(values))
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


# --- §3.2 the design set, whole, required, and without defaults ---------------


@dataclass(frozen=True)
class DesignConstants:
    """All five design constants, together, with no default anywhere.

    Together on purpose. Naming only the constants that appear in a formula
    would leave an implementation free to hard-code `r_runs` or `n_ladder`
    without contradicting a word of the policy, and those two decide the corpus
    cardinality and the `N` selection outright.

    Who consumes what: the fitter uses `q`, `r_runs` and `n_ladder`; the selector
    uses `g`; the verdict uses `m`. No field is carried for symmetry.
    """

    q: Fraction
    m: Fraction
    r_runs: int
    n_ladder: tuple[int, ...]
    g: Fraction

    def __post_init__(self) -> None:
        if not isinstance(self.q, Fraction) or not 0 < self.q < 1:
            raise PolicyRefused(f"q is {self.q!r}; the quantile level lies strictly "
                                "inside (0, 1)")
        if not isinstance(self.m, Fraction) or self.m <= 1:
            raise PolicyRefused(f"M is {self.m!r}; the outer bound is a strict widening "
                                "of the inner one, so M > 1")
        if not isinstance(self.g, Fraction) or self.g < 0:
            raise PolicyRefused(f"G is {self.g!r}; the diminishing-returns margin is "
                                "non-negative")
        canonical_count(self.r_runs, name="R_runs", minimum=2)
        if not self.n_ladder:
            raise PolicyRefused("the N ladder is empty; a finite ladder must contain at "
                                "least one rung, and its last element is the mandatory stop")
        previous = 0
        for rung in self.n_ladder:
            canonical_count(rung, name="an N ladder rung", minimum=1)
            if rung <= previous:
                raise PolicyRefused(
                    f"the N ladder {list(self.n_ladder)} is not strictly increasing at "
                    f"{rung}; an unordered ladder has no well-defined last element and "
                    "therefore no mandatory stop")
            previous = rung

    @classmethod
    def from_committed(cls, *, q: tuple[object, object], m: tuple[object, object],
                       r_runs: object, n_ladder: Sequence[object],
                       g: tuple[object, object]) -> DesignConstants:
        """Build from exactly what was committed: pairs for rationals, ints for counts.

        Every argument is keyword-only and required. There is no default, and
        there is no overload that supplies one.
        """
        return cls(
            q=canonical_rational(q[0], q[1], name="q"),
            m=canonical_rational(m[0], m[1], name="M"),
            r_runs=canonical_count(r_runs, name="R_runs", minimum=2),
            n_ladder=tuple(canonical_count(rung, name="an N ladder rung", minimum=1)
                           for rung in n_ladder),
            g=canonical_rational(g[0], g[1], name="G"),
        )

    @property
    def mandatory_stop(self) -> int:
        """The ladder's last rung. There is no separate maximum to contradict it."""
        return self.n_ladder[-1]

    def as_committed(self) -> dict[str, object]:
        return {"q": as_pair(self.q), "M": as_pair(self.m), "R_runs": self.r_runs,
                "N_ladder": list(self.n_ladder), "G": as_pair(self.g)}


@dataclass(frozen=True)
class Envelope:
    """One rung's fitted inner bound. An empirical output, never a design choice."""

    n: int
    a_abs: Fraction
    r_rel: Fraction

    def __post_init__(self) -> None:
        canonical_count(self.n, name=f"envelope rung n={self.n!r}", minimum=1)
        exact_rational(self.a_abs, name=f"envelope at n={self.n}: A_abs")
        exact_rational(self.r_rel, name=f"envelope at n={self.n}: R_rel")
        if self.a_abs < 0 or self.r_rel < 0:
            raise PolicyRefused(
                f"envelope at n={self.n} has A_abs={self.a_abs}, R_rel={self.r_rel}; a "
                "bound may not be negative anywhere on the duration range")

    def inner(self, t: Fraction) -> Fraction:
        return self.a_abs + self.r_rel * t

    def as_committed(self) -> dict[str, object]:
        return {"n": self.n, "A_abs": as_pair(self.a_abs), "R_rel": as_pair(self.r_rel)}


# --- §1, §2.2, §2.4 the four-way cell verdict --------------------------------


@dataclass(frozen=True)
class CellObservation:
    """One cell as the two runs recorded it. `None` means the run did not produce it."""

    key: str
    median_a: Fraction | None
    median_b: Fraction | None
    exit_a: int | None
    exit_b: int | None
    valid_a: bool
    valid_b: bool

    def __post_init__(self) -> None:
        for label, median in (("median_a", self.median_a), ("median_b", self.median_b)):
            if median is not None:
                exact_rational(median, name=f"{self.key}.{label}")
        for label, code in (("exit_a", self.exit_a), ("exit_b", self.exit_b)):
            if code is not None and (isinstance(code, bool) or not isinstance(code, int)):
                raise PolicyRefused(f"{self.key}.{label} is {code!r}; an exit code is an "
                                    "integer or absent")
        for label, flag in (("valid_a", self.valid_a), ("valid_b", self.valid_b)):
            if not isinstance(flag, bool):
                raise PolicyRefused(f"{self.key}.{label} is {flag!r}; outcome validity is "
                                    "a boolean, and a truthy value is not a boolean")


@dataclass(frozen=True)
class CellVerdict:
    key: str
    verdict: str
    why: str
    delta: Fraction | None = None
    reference_duration: Fraction | None = None
    inner: Fraction | None = None
    outer: Fraction | None = None


def classify_cell(observation: CellObservation, envelope: Envelope,
                  constants: DesignConstants) -> CellVerdict:
    """One cell, four ways.

    The invalid branches come first and they are not failures. An incomparable
    cell says nothing about the instrument, and reporting it as a failure to
    reproduce would invite fixing it by re-running.
    """
    o = observation
    if o.median_a is None or o.median_b is None:
        return CellVerdict(o.key, "invalid",
                           "the cell is present in one run and absent from the other, or "
                           "produced no median; there is nothing to compare")
    if not o.valid_a or not o.valid_b:
        return CellVerdict(o.key, "invalid",
                           f"the recorded outcome is not valid in "
                           f"{'run A' if not o.valid_a else 'run B'}; an invalid cell was "
                           "never a measurement")
    if o.exit_a != o.exit_b:
        return CellVerdict(o.key, "invalid",
                           f"the runs exited {o.exit_a!r} and {o.exit_b!r}; they did not "
                           "measure the same thing, so their durations are not comparable")

    # §2.2: symmetric in both terms. The bound is evaluated at the MIDPOINT, so
    # swapping the runs cannot change the verdict.
    delta = abs(o.median_b - o.median_a)
    t = (o.median_a + o.median_b) / 2
    inner = envelope.inner(t)
    outer = constants.m * inner

    # §2.4: the inner branch is inclusive, the refusing branch is strict. A value
    # landing exactly on a boundary is decided by the written rule.
    if delta <= inner:
        verdict, why = "reproducible", "the change is within the frozen inner bound"
    elif delta > outer:
        verdict, why = "not-reproducible", "the change is outside the frozen outer bound"
    else:
        verdict, why = "inconclusive", "the change lies between the inner and outer bounds"
    return CellVerdict(o.key, verdict, why, delta, t, inner, outer)


def classify_pair(cells: Sequence[CellVerdict],
                  pair_invalidating: Sequence[str]) -> dict[str, object]:
    """The run pair, by strict precedence over its cells. Never by counting.

    There is deliberately no tolerated-failure count. A rule of the form "at most
    K cells may fail" introduces a constant whose only function is to decide how
    much disagreement to forgive, and it will be adjusted the first time K + 1
    cells fail.
    """
    if pair_invalidating:
        return {"verdict": "invalid", "why": "; ".join(pair_invalidating),
                "counts": _counts(cells), "cells": [c.key for c in cells]}
    if not cells:
        return {"verdict": "invalid", "why": "the pair covers no cells at all",
                "counts": _counts(cells), "cells": []}

    counts = _counts(cells)
    for verdict, why in (
        ("invalid", "at least one cell is not comparable, so the pair is not comparable"),
        ("not-reproducible", "at least one cell is outside the frozen outer bound"),
        ("inconclusive", "at least one cell lies between the inner and outer bounds"),
    ):
        if counts[verdict]:
            named = [c.key for c in cells if c.verdict == verdict]
            return {"verdict": verdict, "why": why, "counts": counts, "cells": named}
    return {"verdict": "reproducible", "why": "every cell is within the frozen inner bound",
            "counts": counts, "cells": []}


def _counts(cells: Sequence[CellVerdict]) -> dict[str, int]:
    return {v: sum(1 for c in cells if c.verdict == v) for v in VERDICTS}


# --- §3.3 the empirical fit ---------------------------------------------------


@dataclass(frozen=True)
class Observation:
    """One fitting observation: a reference duration and an observed change."""

    t: Fraction
    y: Fraction

    def __post_init__(self) -> None:
        exact_rational(self.t, name="observation.t")
        exact_rational(self.y, name="observation.y")


def observations_from_medians(medians: Sequence[Fraction], constants: DesignConstants,
                              *, name: str) -> tuple[Observation, ...]:
    """`R_runs` medians in recorded order become `R_runs - 1` consecutive-pair rows.

    Consecutive rather than all pairs, because all-pairs observations are not
    independent and would silently over-weight cells, and because a second run
    following a first is exactly what §9 of the frozen brief tests.
    """
    if len(medians) != constants.r_runs:
        raise PolicyRefused(f"{name}: {len(medians)} medians for R_runs={constants.r_runs}")
    # Defence in depth, and deliberately redundant: `Observation.__post_init__`
    # refuses the same floats a line later, so removing this guard changes the
    # message and not the outcome. It earns its place by naming WHICH median was
    # wrong instead of leaving the caller to work that out from "observation.t",
    # and no mutation can distinguish it -- which is stated here rather than
    # left looking like an untested line.
    for i, median in enumerate(medians):
        exact_rational(median, name=f"{name}: median [{i}]")
    rows = []
    for earlier, later in pairwise(medians):
        rows.append(Observation(t=(earlier + later) / 2, y=abs(later - earlier)))
    return tuple(rows)


def pinball_loss(observations: Sequence[Observation], q: Fraction,
                 a_abs: Fraction, r_rel: Fraction) -> Fraction:
    """The quantile objective, exactly. rho_q(u) = q*u for u >= 0, (q-1)*u below."""
    total = Fraction(0)
    for row in observations:
        u = row.y - (a_abs + r_rel * row.t)
        total += q * u if u >= 0 else (q - 1) * u
    return total


def _candidates(observations: Sequence[Observation]) -> list[tuple[Fraction, Fraction]]:
    """Every vertex an optimum can sit on, per §3.3.

    The objective is piecewise-linear and convex and the feasible region is a
    polyhedron, so an optimum is attained where two conditions are active: a
    residual condition, `a = 0`, or `r = 0`. A floating-point LP solver would not
    be reproducible across platforms; this enumeration is.
    """
    out: list[tuple[Fraction, Fraction]] = []
    for i, first in enumerate(observations):
        for second in observations[i + 1:]:
            if first.t == second.t:
                continue
            r = (second.y - first.y) / (second.t - first.t)
            out.append((first.y - r * first.t, r))
        if first.t != 0:
            out.append((Fraction(0), first.y / first.t))
        out.append((first.y, Fraction(0)))
    out.append((Fraction(0), Fraction(0)))
    return [(a, r) for a, r in out if a >= 0 and r >= 0]


def canonical_minimiser(tied: Iterable[tuple[Fraction, Fraction]]
                       ) -> tuple[Fraction, Fraction]:
    """The ratified tie-break, named so it can be tested as a rule in its own right.

    Among all objective minimisers: the smallest `A_abs`; among those, the
    smallest `R_rel`. Both keys matter, and the second is only reachable when two
    minimisers share an intercept, so it lives here rather than inline where no
    corpus would ever exercise it.

    This is **canonicalisation**, not optimisation. It claims no pointwise
    dominance over the minimisers it passes over -- tied optimal lines can cross,
    and the ratified document records a counterexample. Its only purpose is
    identical constants from identical corpus bytes.
    """
    ordered = sorted(tied)
    if not ordered:
        raise PolicyRefused("no minimiser to canonicalise")
    return ordered[0]


def fit_envelope(n: int, observations: Sequence[Observation],
                 constants: DesignConstants) -> Envelope:
    """One rung's envelope, by exact vertex enumeration and a stated tie-break.

    **Tie-break, in order:** among all objective minimisers represented by the
    enumerated candidate set, the smallest `A_abs`; among those, the smallest
    `R_rel`. This is a deterministic *canonicalisation* rule. It does **not**
    claim pointwise dominance over every other minimiser -- tied optimal lines
    can cross, and the ratified document records a counterexample. Its purpose is
    identical constants from identical corpus bytes, and that is the whole of it.
    """
    if not observations:
        raise PolicyRefused(f"n={n}: no observations to fit")
    for row in observations:
        if row.y < 0:
            raise PolicyRefused(f"n={n}: an observation has y={row.y}; y is an absolute "
                                "difference and cannot be negative")
    if len({row.t for row in observations}) < 2:
        raise PolicyRefused(
            f"n={n}: the corpus has fewer than two distinct reference durations, so a "
            "two-parameter model is not identifiable; refusing rather than guessing")

    candidates = _candidates(observations)
    if not candidates:
        raise PolicyRefused(f"n={n}: no feasible candidate survives A_abs >= 0, R_rel >= 0")

    scored = [(pinball_loss(observations, constants.q, a, r), a, r) for a, r in candidates]
    best = min(loss for loss, _, _ in scored)
    a_abs, r_rel = canonical_minimiser({(a, r) for loss, a, r in scored if loss == best})
    return Envelope(n=n, a_abs=a_abs, r_rel=r_rel)


# --- §3.4 selecting N, with N as a stratum ------------------------------------


def envelope_width(envelope: Envelope, reference_durations: Sequence[Fraction]) -> Fraction:
    """W for one rung: the envelope summed over the named universe's cells."""
    if not reference_durations:
        raise PolicyRefused(f"n={envelope.n}: the workload universe is empty, so its "
                            "envelope width is not defined")
    checked = [exact_rational(t, name=f"n={envelope.n}: reference duration [{i}]")
               for i, t in enumerate(reference_durations)]
    return sum((envelope.inner(t) for t in checked), Fraction(0))


def select_n(envelopes: Mapping[int, Envelope],
             reference_durations: Mapping[int, Sequence[Fraction]],
             constants: DesignConstants) -> dict[str, object]:
    """The smallest rung within `G` of the best width the ladder can achieve.

    Computed from training evidence alone and never revisited afterwards. The
    forbidden rule -- "the smallest N at which the pair reproduces" -- turns the
    stop rule into a starting gun, so `N` is fixed before the validation pair
    exists and is not adjusted once it does.

    Always defined: the rung achieving the minimum satisfies the inequality for
    any G >= 0, so there is no undefined branch.
    """
    missing = [n for n in constants.n_ladder if n not in envelopes]
    if missing:
        raise PolicyRefused(f"no envelope for ladder rungs {missing}; every rung is fitted "
                            "or the selection is over a ladder that was not measured")
    widths = {}
    for n in constants.n_ladder:
        if n not in reference_durations:
            raise PolicyRefused(f"no reference durations for rung n={n}")
        widths[n] = envelope_width(envelopes[n], reference_durations[n])

    best = min(widths.values())
    limit = (1 + constants.g) * best
    for n in constants.n_ladder:                     # ascending: smallest that qualifies
        if widths[n] <= limit:
            return {"selected_n": n,
                    "widths": {k: as_pair(v) for k, v in widths.items()},
                    "best_width": as_pair(best), "limit": as_pair(limit),
                    "why": f"n={n} is the smallest rung whose width is within "
                           f"(1 + G) of the ladder's best"}
    raise PolicyRefused(                              # unreachable for G >= 0
        "no rung is within (1 + G) of the best width, which is impossible for G >= 0 "
        "and means the widths or the margin were not what this function was handed")
