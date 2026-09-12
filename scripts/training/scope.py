"""#263-A calibration — the cross-platform training scope combiner (step 6).

Platform is an **outer training stratum**, never a fifth cell axis. The frozen
four-part cell identity `(rung, engine, workload, regime)` is unchanged, cold and
warm remain distinct cells that pool within a stratum, and observations, medians,
envelopes and widths are **never** pooled or summed across strata.

This module exists because that rule is code which takes a statistical decision,
and §3.6 of the ratified policy requires such code to exist and be
provenance-bound *before* any training data does. It lives outside
`scripts/calibration/` on purpose: the step 4 freeze proves that the frozen root
grew no new file, and it would stop proving that if this landed inside it.

It implements exactly two things the frozen policy cannot express:

    Q_p         the rungs admissible on one stratum
    Q_common    their intersection, and the single selected N

**It does not re-implement the `(1 + G)` admissibility test.** The frozen
`select_n` already computes that and reports `widths` and `limit` alongside its
own pick; `Q_p` is read back off those. A second copy of the margin arithmetic
here would prove only that the two copies agree, which is the defect this PR has
spent thirteen rounds removing. The margin is applied once, inside frozen code.

No clock, no filesystem, no network, no randomness, no numeric default, and no
constant value of any kind: `G` and the ladder arrive in `DesignConstants`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from fractions import Fraction

import policy as pol

OUTCOME_SELECTED = "SELECTED"
OUTCOME_NO_COMMON_N = "NO_COMMON_N"


class ScopeRefused(Exception):
    """Raised rather than returning something that would be read as a result."""


def _exact_from_pair(value: object, *, name: str) -> Fraction:
    """Rebuild an exact rational from the frozen policy's own reduced pair.

    `canonical_rational` does the checking, so the reduced-pair contract has one
    implementation and this module is not a second opinion about what exact means.
    """
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 2:
        raise ScopeRefused(
            f"{name} is {value!r}; the frozen select_n reports every width as a reduced "
            "(numerator, denominator) pair, and a scope decision is taken on nothing else")
    return pol.canonical_rational(value[0], value[1], name=name)


def admissible_rungs(selection: Mapping[str, object], constants: pol.DesignConstants,
                     *, stratum: str) -> tuple[int, ...]:
    """`Q_p`: every ladder rung within `(1 + G)` of THIS stratum's own best width.

    Read off the frozen `select_n` result rather than recomputed. `limit` is that
    function's own `(1 + G) * best`, so the margin cannot drift between the rung
    one stratum picks alone and the rungs both strata will be asked to share.
    """
    widths = selection.get("widths")
    if not isinstance(widths, Mapping):
        raise ScopeRefused(f"{stratum}: the selection carries no widths mapping, so its "
                           "admissible set cannot be read off it")
    limit = _exact_from_pair(selection.get("limit"), name=f"{stratum}: limit")

    admissible: list[int] = []
    for n in constants.n_ladder:
        if n not in widths:
            raise ScopeRefused(
                f"{stratum}: no width for ladder rung n={n}; a stratum missing a rung "
                "cannot be intersected, because a rung that was never measured is not "
                "the same as a rung that was measured and excluded")
        if _exact_from_pair(widths[n], name=f"{stratum}: width at n={n}") <= limit:
            admissible.append(n)

    if not admissible:
        raise ScopeRefused(
            f"{stratum}: no rung is within (1 + G) of its own best width. That is "
            "impossible for G >= 0, so these are not this stratum's own widths and "
            "limit")
    return tuple(admissible)


def combine(selections: Mapping[str, Mapping[str, object]], constants: pol.DesignConstants,
            *, strata: Sequence[str]) -> dict[str, object]:
    """`Q_common`, and the one selected N, or a `NO_COMMON_N` stop.

    The rule is the smallest ladder rung admissible on **every** stratum. It is
    deliberately not `max` of the per-stratum picks, which can name a rung that
    satisfies no stratum's margin; not an averaged width, which lets an unstable
    machine buy the stable one a wider bound; and not "take one platform as the
    reference", which puts the other into D7 with no measurement model of its own.

    `NO_COMMON_N` is an **orchestration** outcome, not a fifth reproducibility
    verdict: the frozen four describe cells and run pairs and are untouched here.
    It means only that the strata admit no shared repetition count under the
    preregistered rule. There is no fallback rung, no stricter-stratum tie-break,
    no second `G` and no second fit.

    On `NO_COMMON_N` the result carries **no** `selected_n` key at all, so a caller
    that reads it without checking the outcome raises `KeyError` instead of
    proceeding on a number that does not exist.
    """
    names = tuple(strata)
    if len(names) < 2:
        raise ScopeRefused(
            f"strata is {list(names)}; a cross-stratum selection over fewer than two "
            "strata is a single-stratum selection wearing the word cross")
    if len(set(names)) != len(names):
        raise ScopeRefused(f"strata {list(names)} names one stratum twice")
    if set(names) != set(selections):
        raise ScopeRefused(
            f"strata {sorted(names)} and selections {sorted(selections)} are not the same "
            "set; a stratum silently dropped here is a platform silently excused from "
            "the intersection")

    per_stratum = {p: admissible_rungs(selections[p], constants, stratum=p) for p in names}
    common = tuple(n for n in constants.n_ladder
                   if all(n in per_stratum[p] for p in names))

    result: dict[str, object] = {
        "outcome": OUTCOME_NO_COMMON_N if not common else OUTCOME_SELECTED,
        "strata": names,
        "admissible_rungs": {p: per_stratum[p] for p in names},
        "q_common": common,
    }
    if not common:
        result["why"] = ("no ladder rung is admissible on every stratum, so the "
                         "preregistered rule selects nothing and step 8 stops")
        return result
    result["selected_n"] = common[0]
    result["why"] = (f"n={common[0]} is the smallest ladder rung admissible on every "
                     f"stratum {list(names)}")
    return result
