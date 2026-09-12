#!/usr/bin/env python3
"""#263-A calibration policy — controls for the pure implementation.

The policy is step 2 of the ratified twelve-step sequence, written before any
training corpus exists. Every claim it makes can therefore be checked without a
clock, and is checked here by running it rather than by reading it:

    calib-no-defaults        no parameter anywhere carries a numeric default
    calib-representation     rationals are reduced pairs, counts are integers
    calib-design-set         all five design constants are required, none default
    calib-cell-verdict       four ways, with the ratified inequalities exact
    calib-symmetry           swapping the two runs never changes a verdict
    calib-aggregation        strict precedence, never a tolerated-failure count
    calib-fit                exact vertex enumeration matches a grid, and is stable
    calib-select-n           the smallest rung within G, always defined
    calib-purity             no clock, no files, no randomness
    calib-exact-domain       a float cannot enter, and no output leaves Fraction

`calib-no-defaults` is the one the owner's last P0 asked for directly: the old
wording named only the constants that appear in a formula, which left an
implementation free to hard-code `R_runs` or the ladder without contradicting it.

Failures print `FAIL[<check>]: <detail>`; nothing stops at the first one.

Run:  python tests/test_calibration_policy.py
"""

from __future__ import annotations

import ast
import inspect
import sys
from fractions import Fraction
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "calibration"))

import policy as pol  # noqa: E402

_FAILURES: list[tuple[str, str]] = []
_PASSES: list[str] = []

POLICY_SOURCE = ROOT / "scripts" / "calibration" / "policy.py"


def fail(check: str, detail: str) -> None:
    _FAILURES.append((check, detail))
    print(f"FAIL[{check}]: {detail}")


def ok(check: str, detail: str = "") -> None:
    _PASSES.append(check)
    print(f"ok[{check}]: {detail}" if detail else f"ok[{check}]")


def _constants(**overrides: object) -> pol.DesignConstants:
    """Synthetic design constants for the controls.

    These are TEST FIXTURES, not proposed values. The policy itself holds none,
    which is what `calib-no-defaults` exists to prove; a control still has to
    hand it something to exercise the arithmetic.
    """
    spec: dict[str, object] = {"q": (3, 4), "m": (2, 1), "r_runs": 3,
                               "n_ladder": (5, 15), "g": (1, 10)}
    spec.update(overrides)
    return pol.DesignConstants.from_committed(**spec)      # type: ignore[arg-type]


# --- the one the owner asked for ---------------------------------------------


def control_no_defaults() -> None:
    """No parameter anywhere carries a numeric default.

    A default is how a constant nobody ratified gets into the code while every
    sentence about required arguments stays technically true. The rule checked
    here is mechanical and total: a default must be absent or `None`. `None`
    is allowed only because the verdict record's optional output fields use it.
    """
    problems = []
    seen = 0
    for name, obj in vars(pol).items():
        if name.startswith("_"):
            continue
        targets = []
        # Only what this module DEFINES. `dataclass` and friends are imported
        # into its namespace and their defaults are not the policy's business --
        # the first version of this control reported ten findings about
        # `dataclass(frozen=False)`, which is a control measuring the wrong thing.
        if inspect.isfunction(obj) and obj.__module__ == pol.__name__:
            targets.append((name, obj))
        elif inspect.isclass(obj) and obj.__module__ == pol.__name__:
            for attr, member in vars(obj).items():
                if inspect.isfunction(member):
                    targets.append((f"{name}.{attr}", member))
                elif isinstance(member, classmethod):
                    targets.append((f"{name}.{attr}", member.__func__))
        for label, fn in targets:
            seen += 1
            for param in inspect.signature(fn).parameters.values():
                if param.default is inspect.Parameter.empty or param.default is None:
                    continue
                problems.append(f"{label}({param.name}=) defaults to {param.default!r}; "
                                "a default is how an unratified constant gets in while "
                                "the sentence about required arguments stays true")

    # And the module must hold no bare number at module level either. A constant
    # does not need to be a default to be a constant.
    for name, obj in vars(pol).items():
        if name.startswith("_"):
            continue
        numeric = isinstance(obj, Fraction) or (isinstance(obj, int)
                                                and not isinstance(obj, bool))
        if numeric:
            problems.append(f"module-level {name} = {obj!r} is a bare number; the policy "
                            "carries no values")

    if seen < 8:
        problems.append(f"only {seen} callables were inspected; the walk is not finding "
                        "the module's surface")
    if problems:
        fail("calib-no-defaults", "; ".join(problems))
    else:
        ok("calib-no-defaults", f"{seen} callables inspected, no numeric default and no "
                                "module-level value anywhere")


def control_design_set() -> None:
    """All five design constants are required, and each is validated."""
    problems = []
    fields = set(pol.DesignConstants.__dataclass_fields__)
    want = {"q", "m", "r_runs", "n_ladder", "g"}
    if fields != want:
        problems.append(f"DesignConstants carries {sorted(fields)}, want {sorted(want)}; "
                        "R_runs and the ladder decide corpus cardinality and N selection "
                        "and cannot live outside the design set")

    for missing in sorted(want):
        spec = {"q": (3, 4), "m": (2, 1), "r_runs": 3, "n_ladder": (5, 15), "g": (1, 10)}
        del spec[missing]
        try:
            pol.DesignConstants.from_committed(**spec)      # type: ignore[arg-type]
        except TypeError:
            pass
        except Exception as exc:
            problems.append(f"omitting {missing} raised {type(exc).__name__}, not TypeError")
        else:
            problems.append(f"DesignConstants was built without {missing}; it has a default")

    # Ranges, each refused by the field that owns it.
    for label, overrides in (
        ("q at 1", {"q": (1, 1)}), ("q at 0", {"q": (0, 1)}),
        ("M at 1", {"m": (1, 1)}), ("M below 1", {"m": (1, 2)}),
        ("G below 0", {"g": (-1, 10)}),
        ("R_runs below 2", {"r_runs": 1}),
        ("an empty ladder", {"n_ladder": ()}),
        ("an unordered ladder", {"n_ladder": (15, 5)}),
        ("a ladder with a repeat", {"n_ladder": (5, 5)}),
        ("a zero rung", {"n_ladder": (0, 5)}),
    ):
        try:
            _constants(**overrides)
        except pol.PolicyRefused:
            pass
        except Exception as exc:
            problems.append(f"{label} raised {type(exc).__name__}, not PolicyRefused: {exc}")
        else:
            problems.append(f"{label} was accepted")

    c = _constants()
    if c.mandatory_stop != c.n_ladder[-1]:
        problems.append("the mandatory stop is not the ladder's last rung")
    if c.as_committed()["q"] != (3, 4):
        problems.append(f"as_committed does not round-trip q: {c.as_committed()['q']}")

    if problems:
        fail("calib-design-set", "; ".join(problems))
    else:
        ok("calib-design-set", "all five constants required; every range refused by its "
                               "own field; the ladder's last rung is the mandatory stop")


def control_representation() -> None:
    """Rationals are reduced pairs. Counts are integers. Floats are refused."""
    problems = []

    for label, args in (
        ("a float numerator", (0.95, 1)), ("a float denominator", (19, 20.0)),
        ("a decimal string", ("0.95", 1)), ("a bool", (True, 1)),
        ("a zero denominator", (1, 0)), ("a negative denominator", (19, -20)),
        ("an unreduced pair", (10, 20)),
    ):
        try:
            pol.canonical_rational(args[0], args[1], name="probe")
        except pol.PolicyRefused:
            pass
        except Exception as exc:
            problems.append(f"{label} raised {type(exc).__name__}: {exc}")
        else:
            problems.append(f"{label} was accepted as canonical")

    if pol.canonical_rational(19, 20, name="probe") != Fraction(19, 20):
        problems.append("a reduced pair did not round-trip")
    if pol.as_pair(Fraction(19, 20)) != (19, 20):
        problems.append("as_pair did not produce the canonical pair")

    for label, value in (("a float count", 5.0), ("a bool count", True),
                         ("a string count", "5")):
        try:
            pol.canonical_count(value, name="probe", minimum=2)
        except pol.PolicyRefused:
            pass
        except Exception as exc:
            problems.append(f"{label} raised {type(exc).__name__}: {exc}")
        else:
            problems.append(f"{label} was accepted as a count")

    # A count is an integer, NOT the pair (n, 1): the ladder takes ints.
    try:
        _constants(n_ladder=((5, 1), (15, 1)))
    except pol.PolicyRefused:
        pass
    except Exception as exc:
        problems.append(f"a ladder of pairs raised {type(exc).__name__}: {exc}")
    else:
        problems.append("a ladder written as rational pairs was accepted; counts and "
                        "rationals are different kinds and the representation says so")

    # Exact median: an even count must not go through a float.
    got = pol.exact_median([Fraction(1), Fraction(2)], name="probe")
    if got != Fraction(3, 2) or not isinstance(got, Fraction):
        problems.append(f"the median of 1 and 2 is {got!r}, not the exact 3/2")

    if problems:
        fail("calib-representation", "; ".join(problems))
    else:
        ok("calib-representation", "floats, decimal strings, bools, zero and negative "
                                   "denominators and unreduced pairs are all refused; "
                                   "counts are integers and medians stay exact")


# --- the verdict --------------------------------------------------------------


def _cell(a: Fraction, b: Fraction, key: str = "cell") -> pol.CellObservation:
    return pol.CellObservation(key=key, median_a=a, median_b=b, exit_a=0, exit_b=0,
                               valid_a=True, valid_b=True)


def control_cell_verdict() -> None:
    """Four ways, with the ratified inequalities landing exactly where written."""
    problems = []
    c = _constants(m=(2, 1))
    env = pol.Envelope(n=5, a_abs=Fraction(10), r_rel=Fraction(0))   # inner 10, outer 20

    # Boundaries: inner inclusive, outer strict.
    for delta, want in ((Fraction(0), "reproducible"), (Fraction(10), "reproducible"),
                        (Fraction(11), "inconclusive"), (Fraction(20), "inconclusive"),
                        (Fraction(21), "not-reproducible")):
        got = pol.classify_cell(_cell(Fraction(100), Fraction(100) + delta), env, c)
        if got.verdict != want:
            problems.append(f"delta {delta} against inner 10 / outer 20 read as "
                            f"{got.verdict}, want {want}")

    # The invalid branches, each by the condition that owns it.
    for label, obs in (
        ("a missing median", pol.CellObservation("c", None, Fraction(1), 0, 0, True, True)),
        ("an invalid outcome", pol.CellObservation("c", Fraction(1), Fraction(1), 0, 0,
                                                   False, True)),
        ("disagreeing exit codes", pol.CellObservation("c", Fraction(1), Fraction(1), 0, 2,
                                                       True, True)),
    ):
        got = pol.classify_cell(obs, env, c)
        if got.verdict != "invalid":
            problems.append(f"{label} read as {got.verdict}, want invalid")

    # A zero bound admits exact agreement and nothing else.
    zero = pol.Envelope(n=5, a_abs=Fraction(0), r_rel=Fraction(0))
    if pol.classify_cell(_cell(Fraction(5), Fraction(5)), zero, c).verdict != "reproducible":
        problems.append("a zero bound refused two identical medians")
    if pol.classify_cell(_cell(Fraction(5), Fraction(6)), zero, c).verdict != "not-reproducible":
        problems.append("a zero bound did not refuse a non-zero change")

    # The bound is evaluated at the MIDPOINT, not at either run.
    slope = pol.Envelope(n=5, a_abs=Fraction(0), r_rel=Fraction(1, 10))
    got = pol.classify_cell(_cell(Fraction(100), Fraction(120)), slope, c)
    if got.reference_duration != Fraction(110):
        problems.append(f"the reference duration is {got.reference_duration}, not the "
                        "midpoint 110")

    if problems:
        fail("calib-cell-verdict", "; ".join(problems))
    else:
        ok("calib-cell-verdict", "inner inclusive, outer strict, the three invalid "
                                 "conditions each refused by name, a zero bound admits "
                                 "only exact agreement, and the bound sits at the midpoint")


def control_symmetry() -> None:
    """Swapping the two runs never changes a verdict. Exhaustively, on a grid.

    This is the defect the policy exists to remove: the incumbent rule divides by
    whichever run was recorded first, so for every positive tolerance there is a
    band where the verdict depends on run order and nothing else.
    """
    problems = []
    c = _constants(m=(3, 2))
    grid = [Fraction(n) for n in range(1, 40)]
    checked = 0
    for env in (pol.Envelope(5, Fraction(1), Fraction(0)),
                pol.Envelope(5, Fraction(0), Fraction(1, 20)),
                pol.Envelope(5, Fraction(2), Fraction(1, 10))):
        for a, b in product(grid, repeat=2):
            forward = pol.classify_cell(_cell(a, b), env, c).verdict
            reverse = pol.classify_cell(_cell(b, a), env, c).verdict
            checked += 1
            if forward != reverse:
                problems.append(f"medians {a} then {b} read {forward}, reversed {reverse}, "
                                f"under A_abs={env.a_abs} R_rel={env.r_rel}")
                break
        if problems:
            break
    if problems:
        fail("calib-symmetry", "; ".join(problems))
    else:
        ok("calib-symmetry", f"{checked} ordered median pairs across three envelopes, "
                             "and no verdict depends on which run was recorded first")


def control_aggregation() -> None:
    """Strict precedence over cells, and never a tolerated-failure count."""
    problems = []

    def verdicts(*names: str) -> list[pol.CellVerdict]:
        return [pol.CellVerdict(f"c{i}", n, "") for i, n in enumerate(names)]

    cases = [
        (("reproducible",) * 5, "reproducible"),
        (("reproducible", "inconclusive", "reproducible"), "inconclusive"),
        (("reproducible", "not-reproducible", "inconclusive"), "not-reproducible"),
        (("invalid", "not-reproducible", "inconclusive"), "invalid"),
        (("reproducible",) * 99 + ("not-reproducible",), "not-reproducible"),
    ]
    for names, want in cases:
        got = pol.classify_pair(verdicts(*names), [])
        if got["verdict"] != want:
            problems.append(f"{len(names)} cells {sorted(set(names))} aggregated to "
                            f"{got['verdict']}, want {want}")

    # One bad cell in a hundred is still a bad pair. If that ever stops being
    # true, a tolerated-failure count has appeared.
    many = pol.classify_pair(verdicts(*(("reproducible",) * 99 + ("not-reproducible",))), [])
    if many["verdict"] != "not-reproducible":
        problems.append("1 failing cell among 100 did not fail the pair; a tolerated "
                        "failure count has appeared")

    if pol.classify_pair(verdicts("reproducible"), ["environment fingerprint mismatch"]
                         )["verdict"] != "invalid":
        problems.append("a pair-level invalidating condition did not make the pair invalid")
    if pol.classify_pair([], [])["verdict"] != "invalid":
        problems.append("a pair covering no cells was not invalid")

    if problems:
        fail("calib-aggregation", "; ".join(problems))
    else:
        ok("calib-aggregation", "precedence invalid > not-reproducible > inconclusive > "
                                "reproducible; one failing cell in a hundred still fails "
                                "the pair; a pair-level condition overrides every cell")


# --- the fit ------------------------------------------------------------------


def control_fit() -> None:
    """Exact vertex enumeration finds the optimum, and finds the same one twice."""
    problems = []
    c = _constants(q=(1, 2), r_runs=3)

    def rows(pairs: list[tuple[int, int]]) -> list[pol.Observation]:
        return [pol.Observation(Fraction(t), Fraction(y)) for t, y in pairs]

    # Against a dense grid. The grid can only ever tie or lose, so a grid point
    # beating the enumeration would falsify the construction the policy rests on.
    data = rows([(1, 3), (4, 5), (9, 12), (16, 14), (25, 30)])
    fitted = pol.fit_envelope(5, data, c)
    best = pol.pinball_loss(data, c.q, fitted.a_abs, fitted.r_rel)
    steps = 60
    for ia in range(steps + 1):
        a = Fraction(ia * 30, steps)
        for ir in range(steps + 1):
            r = Fraction(ir * 3, steps)
            if pol.pinball_loss(data, c.q, a, r) < best:
                problems.append(f"a grid point A={a} R={r} beat the enumerated optimum "
                                f"A={fitted.a_abs} R={fitted.r_rel}")
                break
        if problems:
            break

    # Same bytes, same constants. That is the whole point of the tie-break.
    again = pol.fit_envelope(5, rows([(1, 3), (4, 5), (9, 12), (16, 14), (25, 30)]), c)
    if (again.a_abs, again.r_rel) != (fitted.a_abs, fitted.r_rel):
        problems.append(f"two fits of identical data gave {(fitted.a_abs, fitted.r_rel)} "
                        f"and {(again.a_abs, again.r_rel)}")

    # A falling corpus: every pair-line has negative slope and is filtered out, so
    # the optimum can ONLY sit on the a = 0 or r = 0 boundary. Checking
    # non-negativity alone was not enough -- dropping both boundary families
    # collapses the fit to the corner (0, 0), which is non-negative and wrong.
    # The grid decides it instead.
    falling_rows = rows([(1, 30), (10, 20), (20, 5)])
    falling = pol.fit_envelope(5, falling_rows, c)
    if falling.a_abs < 0 or falling.r_rel < 0:
        problems.append(f"a falling corpus produced A={falling.a_abs} R={falling.r_rel}; "
                        "a bound may not be negative anywhere")
    falling_loss = pol.pinball_loss(falling_rows, c.q, falling.a_abs, falling.r_rel)
    for ia in range(steps + 1):
        a = Fraction(ia * 40, steps)
        for ir in range(steps + 1):
            r = Fraction(ir * 3, steps)
            if pol.pinball_loss(falling_rows, c.q, a, r) < falling_loss:
                problems.append(f"on a falling corpus a grid point A={a} R={r} beat the "
                                f"enumerated A={falling.a_abs} R={falling.r_rel}; the "
                                "boundary candidates are not being enumerated")
                break
        else:
            continue
        break

    # The tie-break as a rule, both keys. The second key is only reachable when
    # two minimisers share an intercept, which no natural corpus in this control
    # produces, so it is exercised directly rather than left unverified.
    if pol.canonical_minimiser({(Fraction(1), Fraction(5)), (Fraction(1), Fraction(2)),
                                (Fraction(3), Fraction(0))}) != (Fraction(1), Fraction(2)):
        problems.append("the tie-break did not take the smallest R_rel among minimisers "
                        "sharing the smallest A_abs")
    if pol.canonical_minimiser({(Fraction(9), Fraction(0)), (Fraction(2), Fraction(7))}
                               ) != (Fraction(2), Fraction(7)):
        problems.append("the tie-break did not take the smallest A_abs")
    try:
        pol.canonical_minimiser(set())
    except pol.PolicyRefused:
        pass
    else:
        problems.append("canonicalising an empty minimiser set returned a value")

    # The tie-break, on a corpus whose optimum is genuinely NOT unique. Both
    # (28/5, 9/5) and (11, 0) attain the same loss here; the ratified rule takes
    # the smallest A_abs. Without a stated tie-break two correct implementations
    # return different constants, which is the entire reason the rule exists.
    tied_rows = rows([(8, 20), (8, 10), (3, 11)])
    tied_fit = pol.fit_envelope(5, tied_rows, c)
    rival = (Fraction(11), Fraction(0))
    if pol.pinball_loss(tied_rows, c.q, *rival) != pol.pinball_loss(
            tied_rows, c.q, tied_fit.a_abs, tied_fit.r_rel):
        problems.append("the tied corpus no longer has two minimisers, so the tie-break "
                        "is not being exercised at all")
    elif (tied_fit.a_abs, tied_fit.r_rel) != (Fraction(28, 5), Fraction(9, 5)):
        problems.append(f"the tie-break returned A={tied_fit.a_abs} R={tied_fit.r_rel}; "
                        "the ratified rule takes the smallest A_abs, which is 28/5")

    # Fail-closed, three ways.
    for label, args in (
        ("no observations", []),
        ("one distinct duration", rows([(5, 1), (5, 2), (5, 3)])),
    ):
        try:
            pol.fit_envelope(5, args, c)
        except pol.PolicyRefused:
            pass
        except Exception as exc:
            problems.append(f"{label} raised {type(exc).__name__}: {exc}")
        else:
            problems.append(f"{label} was fitted instead of refused")
    try:
        pol.fit_envelope(5, [pol.Observation(Fraction(1), Fraction(-1)),
                             pol.Observation(Fraction(2), Fraction(1))], c)
    except pol.PolicyRefused:
        pass
    else:
        problems.append("a negative y was fitted; y is an absolute difference")

    # Observations come from CONSECUTIVE pairs, R_runs - 1 of them.
    obs = pol.observations_from_medians([Fraction(10), Fraction(14), Fraction(12)],
                                        c, name="probe")
    if len(obs) != c.r_runs - 1:
        problems.append(f"{len(obs)} observations from {c.r_runs} medians")
    if (obs[0].t, obs[0].y) != (Fraction(12), Fraction(4)):
        problems.append(f"the first observation is {(obs[0].t, obs[0].y)}, want midpoint 12 "
                        "and absolute change 4")
    try:
        pol.observations_from_medians([Fraction(1), Fraction(2)], c, name="probe")
    except pol.PolicyRefused:
        pass
    else:
        problems.append("a corpus with the wrong number of runs per cell was accepted")

    if problems:
        fail("calib-fit", "; ".join(problems))
    else:
        ok("calib-fit", "no grid point beats the enumerated optimum; identical data give "
                        "identical constants; the bound stays non-negative; and an empty, "
                        "rank-deficient, negative or mis-sized corpus is refused")


def control_select_n() -> None:
    """The smallest rung within G of the ladder's best width, and always defined."""
    problems = []
    c = _constants(n_ladder=(5, 15, 45), g=(1, 10))
    durations = {n: [Fraction(100), Fraction(200)] for n in c.n_ladder}

    # 15 is best; 5 is within 10% of it; 5 must win because it is smaller.
    envs = {5: pol.Envelope(5, Fraction(0), Fraction(105, 1000)),
            15: pol.Envelope(15, Fraction(0), Fraction(100, 1000)),
            45: pol.Envelope(45, Fraction(0), Fraction(99, 1000))}
    got = pol.select_n(envs, durations, c)
    if got["selected_n"] != 5:
        problems.append(f"selected n={got['selected_n']}; n=5 is within (1 + G) of the "
                        "best width and is the smallest such rung")

    # Widen the gap and the small rung must lose.
    envs[5] = pol.Envelope(5, Fraction(0), Fraction(500, 1000))
    got = pol.select_n(envs, durations, c)
    if got["selected_n"] != 15:
        problems.append(f"selected n={got['selected_n']} when n=5 is far outside the "
                        "margin; want 15")

    # G = 0 selects the argmin exactly, and a selection always exists.
    strict = _constants(n_ladder=(5, 15, 45), g=(0, 1))
    if pol.select_n(envs, durations, strict)["selected_n"] != 45:
        problems.append("G = 0 did not select the ladder's best rung")

    for label, kwargs in (("a missing envelope", {"envelopes": {5: envs[5]}}),
                          ("missing reference durations", {"durations": {5: durations[5]}})):
        e = kwargs.get("envelopes", envs)
        d = kwargs.get("durations", durations)
        try:
            pol.select_n(e, d, c)                     # type: ignore[arg-type]
        except pol.PolicyRefused:
            pass
        except Exception as exc:
            problems.append(f"{label} raised {type(exc).__name__}: {exc}")
        else:
            problems.append(f"{label} was selected over instead of refused")

    try:
        pol.envelope_width(envs[5], [])
    except pol.PolicyRefused:
        pass
    else:
        problems.append("an empty workload universe produced a width")

    if problems:
        fail("calib-select-n", "; ".join(problems))
    else:
        ok("calib-select-n", "the smallest rung within (1 + G) of the best width wins; a "
                             "rung far outside the margin loses; G = 0 picks the argmin; "
                             "and a missing rung or empty universe is refused")


def control_exact_domain() -> None:
    """A float cannot enter the policy, and nothing it computes leaves the exact domain.

    The boundary held at exactly one entry point once: `from_committed`. Every
    other quantitative object -- `Envelope`, `Observation`, `CellObservation` --
    took whatever it was handed. That is not a typing nicety, because
    `Fraction * float` is a **float** in Python: one float anywhere made the
    fitted `R_rel`, the bound and the comparison that decides the verdict all
    floating point. A module that refused a floating-point LP solver on
    exactness grounds was then deciding its boundaries by rounding direction
    through the front door of a dataclass.

    Both halves are checked here. A float must be refused rather than converted,
    since `Fraction(0.1)` preserves the binary error with impeccable fidelity.
    And the pipeline's outputs must all still be `Fraction`, or the refusals
    above are guarding a door in a building with no walls.
    """
    problems = []
    c = _constants()
    good_env = pol.Envelope(n=5, a_abs=Fraction(1), r_rel=Fraction(1, 10))

    refusals = [
        ("Envelope A_abs as float",
         lambda: pol.Envelope(n=5, a_abs=0.1, r_rel=Fraction(0))),
        ("Envelope R_rel as float",
         lambda: pol.Envelope(n=5, a_abs=Fraction(0), r_rel=0.2)),
        ("Envelope A_abs as int",
         lambda: pol.Envelope(n=5, a_abs=1, r_rel=Fraction(0))),
        ("Observation t as float", lambda: pol.Observation(t=3.14, y=Fraction(1))),
        ("Observation y as float", lambda: pol.Observation(t=Fraction(1), y=0.2)),
        ("CellObservation median as float",
         lambda: pol.CellObservation("x", 1.1, Fraction(1), 0, 0, True, True)),
        ("CellObservation exit code as float",
         lambda: pol.CellObservation("x", Fraction(1), Fraction(1), 0.0, 0, True, True)),
        ("CellObservation validity as a truthy non-boolean",
         lambda: pol.CellObservation("x", Fraction(1), Fraction(1), 0, 0, 1, True)),
        ("exact_median over floats", lambda: pol.exact_median([0.1, 0.2], name="probe")),
        ("envelope_width over float durations",
         lambda: pol.envelope_width(good_env, [0.5])),
        # This one is caught twice: by the guard in `observations_from_medians`
        # and, if that guard is removed, by `Observation` a line later. The
        # refusal is therefore load-bearing but the guard itself is defence in
        # depth, and no mutation of it can change the outcome. Recorded so the
        # line does not read as untested coverage.
        ("observations_from_medians over floats",
         lambda: pol.observations_from_medians([0.1, 0.2, 0.3], c, name="probe")),
        # The public ARITHMETIC surface, not just the constructors. Each of these
        # was open after the first repair, and the first two can actually corrupt
        # a computation: `inner` is where the envelope meets a caller's duration,
        # and `pinball_loss` is the objective that decides the fit.
        ("Envelope.inner with a float duration", lambda: good_env.inner(0.1)),
        ("pinball_loss with a float q",
         lambda: pol.pinball_loss([pol.Observation(Fraction(1), Fraction(1))], 0.75,
                                  Fraction(0), Fraction(0))),
        ("pinball_loss with a float A_abs",
         lambda: pol.pinball_loss([pol.Observation(Fraction(1), Fraction(1))], c.q,
                                  0.1, Fraction(0))),
        ("pinball_loss with a float R_rel",
         lambda: pol.pinball_loss([pol.Observation(Fraction(1), Fraction(1))], c.q,
                                  Fraction(0), 0.2)),
        ("canonical_minimiser over float pairs",
         lambda: pol.canonical_minimiser({(0.1, 0.2), (Fraction(9), Fraction(0))})),
        # The serialiser cannot corrupt a fit, but a surface that fails closed
        # everywhere except one function is a surface somebody will later argue
        # about. It died with AttributeError before this.
        ("as_pair of a float", lambda: pol.as_pair(0.5)),
    ]
    for label, thunk in refusals:
        try:
            thunk()
        except pol.PolicyRefused:
            pass
        except Exception as exc:
            problems.append(f"{label} raised {type(exc).__name__}, not PolicyRefused: {exc}")
        else:
            problems.append(f"{label} was accepted; a float that enters here makes every "
                            "downstream quantity floating point")

    # The positive half. Drive a full fit and verdict and check the TYPES that
    # come out, not just that the refusals fire.
    rows = [pol.Observation(Fraction(1), Fraction(3)), pol.Observation(Fraction(4), Fraction(5)),
            pol.Observation(Fraction(9), Fraction(12))]
    fitted = pol.fit_envelope(5, rows, c)
    verdict = pol.classify_cell(
        pol.CellObservation("x", Fraction(100), Fraction(110), 0, 0, True, True), fitted, c)
    width = pol.envelope_width(fitted, [Fraction(100), Fraction(200)])
    minimised = pol.canonical_minimiser({(Fraction(1), Fraction(2)), (Fraction(3), Fraction(0))})
    produced = {"A_abs": fitted.a_abs, "R_rel": fitted.r_rel, "delta": verdict.delta,
                "reference_duration": verdict.reference_duration, "inner": verdict.inner,
                "outer": verdict.outer, "width": width,
                "envelope.inner": fitted.inner(Fraction(100)),
                "minimiser A_abs": minimised[0], "minimiser R_rel": minimised[1],
                "loss": pol.pinball_loss(rows, c.q, fitted.a_abs, fitted.r_rel),
                "median": pol.exact_median([Fraction(1), Fraction(2)], name="probe")}
    for label, value in produced.items():
        if not isinstance(value, Fraction):
            problems.append(f"{label} came out as {type(value).__name__} = {value!r}; the "
                            "computation left the exact domain")
    pair = pol.as_pair(Fraction(19, 20))
    if pair != (19, 20) or not all(isinstance(x, int) for x in pair):
        problems.append(f"as_pair produced {pair!r}, not the canonical integer pair")

    # The root cause of this finding was four forgotten `exact_rational()` calls,
    # so the durable fix is not four more refusal cases -- it is a check that
    # fails the next time a public entry point appears without one. Every public
    # callable the module defines is enumerated and must be accounted for here.
    covered = {
        # guarded, and exercised by a refusal case above
        "Envelope.inner", "as_pair", "canonical_minimiser", "canonical_rational",
        "canonical_count", "exact_rational", "exact_median", "envelope_width",
        "observations_from_medians", "pinball_loss",
        "DesignConstants.from_committed",
        # take already-validated policy objects, never a bare number
        "classify_cell", "classify_pair", "fit_envelope", "select_n",
        "DesignConstants.as_committed", "Envelope.as_committed",
    }
    public = set()
    for name, obj in vars(pol).items():
        if name.startswith("_"):
            continue
        if inspect.isfunction(obj) and obj.__module__ == pol.__name__:
            public.add(name)
        elif inspect.isclass(obj) and obj.__module__ == pol.__name__:
            for attr, member in vars(obj).items():
                fn = member.__func__ if isinstance(member, classmethod) else member
                if inspect.isfunction(fn) and not attr.startswith("__"):
                    public.add(f"{name}.{attr}")
    unaccounted = sorted(public - covered)
    vanished = sorted(covered - public)
    if unaccounted:
        problems.append(f"public entry points with no exact-domain accounting: "
                        f"{unaccounted}; each is a place a float can enter, which is "
                        "exactly how the last four got in")
    if vanished:
        problems.append(f"this control still accounts for {vanished}, which the module no "
                        "longer defines; the list has drifted from the surface")

    if problems:
        fail("calib-exact-domain", "; ".join(problems))
    else:
        ok("calib-exact-domain", f"{len(refusals)} float and non-exact inputs refused at "
                                 f"the door rather than converted, all {len(produced)} "
                                 f"computed quantities come back Fraction, and all "
                                 f"{len(public)} public entry points are accounted for")


def control_purity() -> None:
    """No clock, no files, no randomness, no global state. Read from the source."""
    problems = []
    tree = ast.parse(POLICY_SOURCE.read_text(encoding="utf-8"))
    allowed = {"collections.abc", "dataclasses", "fractions", "itertools", "math",
               "__future__"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = imported - allowed
    if forbidden:
        problems.append(f"the policy imports {sorted(forbidden)}; a module that decides "
                        "admissibility must not reach a clock, a file or a generator")

    # No mutable module-level state that a second call could observe.
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                mutable = isinstance(node.value, (ast.List, ast.Dict, ast.Set))
                if isinstance(target, ast.Name) and mutable:
                    problems.append(f"module-level mutable {target.id}; the policy must "
                                    "be pure and a shared container is not")

    if problems:
        fail("calib-purity", "; ".join(problems))
    else:
        ok("calib-purity", f"imports are {sorted(imported)} and nothing else; no mutable "
                           "module-level state")


def run() -> int:
    control_no_defaults()
    control_design_set()
    control_representation()
    control_cell_verdict()
    control_symmetry()
    control_aggregation()
    control_fit()
    control_select_n()
    control_exact_domain()
    control_purity()
    print()
    print(f"calibration policy controls: {len(_PASSES)} passed, {len(_FAILURES)} failed")
    return 1 if _FAILURES else 0


if __name__ == "__main__":
    sys.exit(run())
