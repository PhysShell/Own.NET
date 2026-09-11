#!/usr/bin/env python3
"""#263-A Round 7 — controls for the apparatus, before any measurement exists.

The apparatus is a classifier and a structural preflight. Both can be exercised
exhaustively without a clock, and both are checked here by running them rather
than by reading them:

    round7-outcome-exclusivity  the ratified rules never fire twice at once
    round7-zero-guard           A == 0 refuses; B == 0 alone does NOT
    round7-boundaries           every rule's exact edge lands where it was ratified
    round7-regime-reading       n-disagreement is P5; a cold/warm split is not
    round7-preflight            B1-B4 pass on healthy arms and each refuses its own damage

The exclusivity control matters most. The previous draft's outcome table let one
dataset satisfy two contradictory verdicts, and nothing in the process that
produced it would have noticed. It is checked here over an exact rational grid,
and checked in the other direction too: the old overlapping rule is handed to
the same census, which must report it broken. A control that only ever sees
correct input is a control nobody has tested.

Failures print `FAIL[<check>]: <detail>`; nothing stops at the first one.

Run:  python tests/test_round7_apparatus.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from fractions import Fraction
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "round7"))

import classify as cl  # noqa: E402
import preflight as pf  # noqa: E402
from elfread import Elf64  # noqa: E402

_FAILURES: list[tuple[str, str]] = []
_PASSES: list[str] = []


def fail(check: str, detail: str) -> None:
    _FAILURES.append((check, detail))
    print(f"FAIL[{check}]: {detail}")


def ok(check: str, detail: str = "") -> None:
    _PASSES.append(check)
    print(f"ok[{check}]: {detail}" if detail else f"ok[{check}]")


# --- the classifier --------------------------------------------------------

# Sixths, so the ratified edges -- 3/2, 3, 2/3, 2 -- all land exactly on grid
# points instead of near them. Floats would decide those edges by rounding.
_GRID = tuple(Fraction(n, 6) for n in range(0, 37))


def _census(rules_fired) -> dict[tuple[str, ...], list[tuple[Fraction, ...]]]:
    """Every grid point where more than one rule fires, keyed by which rules."""
    out: dict[tuple[str, ...], list[tuple[Fraction, ...]]] = {}
    for a, b, c in product(_GRID, repeat=3):
        fired = rules_fired(a, b, c)
        if len(fired) > 1:
            out.setdefault(tuple(sorted(fired)), []).append((a, b, c))
    return out


def _old_rules_fired(a, b, c) -> tuple[str, ...]:
    """The PREVIOUS draft's rules, kept only so the census can reject them.

    The single difference is P1's missing `C > 1.5A` clause. That one absence is
    what let A=1, B=3, C=1.4 be both "the padded image explains it" and "the
    phenomenon never reproduced".
    """
    A, B, C = Fraction(a), Fraction(b), Fraction(c)
    three_halves = Fraction(3, 2)
    fired = []
    if C <= three_halves * A:
        fired.append("P4")
    if B >= 3 * A and C <= three_halves * B:          # no C > 1.5A guard
        fired.append("P1")
    if B <= three_halves * A and C >= 3 * A:
        fired.append("P2")
    if B >= 3 * A and C >= 2 * B:
        fired.append("P3")
    return tuple(fired)


def control_outcome_exclusivity() -> None:
    """The ratified rules overlap only where A and B are both exactly zero.

    Checked in both directions. The real rules must be clean everywhere else;
    the old rules must be caught. Without the second half this control would
    pass just as happily against a census that never looks at anything.
    """
    problems = []
    overlaps = _census(cl.rules_fired)

    # (1) The claim the preregistration now makes, verbatim.
    bad = {k: v for k, v in overlaps.items() if any(a != 0 or b != 0 for a, b, _ in v)}
    if bad:
        first = next(iter(bad.items()))
        problems.append(f"the rules overlap away from A=B=0: {first[0]} at "
                        f"{[str(x) for x in first[1][0]]}")
    if any("P1" in k for k in overlaps):
        problems.append("P1 overlaps another rule; the ratified set says it is disjoint "
                        "unconditionally, because C > 1.5A cannot hold once the other "
                        "clauses force B and C to zero")
    # (2) And the overlaps that DO exist must exist, or this proves nothing.
    if not overlaps:
        problems.append("no overlap was found anywhere, including at A=B=0 where P2 and "
                        "P3 provably coincide — the census is not evaluating the rules")

    # (3) The other direction: the old rules must be caught, away from zero.
    old = _census(_old_rules_fired)
    old_nonzero = {k: v for k, v in old.items() if any(a != 0 or b != 0 for a, b, _ in v)}
    if not old_nonzero:
        problems.append("the previous draft's overlapping P1 was NOT caught by this "
                        "census, so the census cannot detect the defect it exists for")
    # And the owner's exact counterexample, at the exact numbers.
    fired_old = _old_rules_fired(1, 3, Fraction(7, 5))
    if sorted(fired_old) != ["P1", "P4"]:
        problems.append(f"A=1, B=3, C=1.4 fired {sorted(fired_old)} under the old rules; "
                        "the recorded defect was P1 and P4 together")
    fired_new = cl.rules_fired(1, 3, Fraction(7, 5))
    if sorted(fired_new) != ["P4"]:
        problems.append(f"A=1, B=3, C=1.4 fires {sorted(fired_new)} under the RATIFIED "
                        "rules; it must be P4 alone")

    # (4) The fail-closed backstop: ambiguity raises rather than picking.
    try:
        cl.outcome_at(0, 0, 5)
    except cl.AmbiguousOutcome:
        pass
    except Exception as exc:
        problems.append(f"an ambiguous triple raised {type(exc).__name__}, not "
                        f"AmbiguousOutcome: {exc}")
    else:
        problems.append("A=0, B=0, C=5 satisfies both P2 and P3 and the classifier "
                        "returned a single answer anyway — it chose")

    if problems:
        fail("round7-outcome-exclusivity", "; ".join(problems))
    else:
        ok("round7-outcome-exclusivity",
           f"over {len(_GRID) ** 3} exact rational triples the ratified rules overlap "
           f"only at A=B=0 ({sum(len(v) for v in overlaps.values())} such points, "
           f"{sorted(overlaps)}), P1 overlaps nothing, and the previous draft's P1 is "
           "still detected as broken")


def control_zero_guard() -> None:
    """A == 0 refuses the regime. B == 0 alone is a result, not a refusal."""
    problems = []

    def regime(a5, b5, c5, a15=None, b15=None, c15=None):
        """Classify, turning a raise into a reportable finding.

        Without this the control dies on a traceback the moment the guard is
        removed -- A=B=C=0 fires P2, P3 and P4 at once, so the classifier raises
        AmbiguousOutcome and the run ends with a stack trace naming the raise
        site and no FAIL line naming the cause. That exact shape was recorded as
        a finding one round ago; it is not allowed to reappear here.
        """
        second = (a5 if a15 is None else a15, b5 if b15 is None else b15,
                  c5 if c15 is None else c15)
        try:
            return cl.regime_outcome("process-cold", {5: (a5, b5, c5), 15: second})
        except cl.ClassifierError as exc:
            problems.append(f"A={a5}, B={b5}, C={c5} raised {type(exc).__name__} instead "
                            f"of being routed to P5 by the zero-A guard: {exc}")
            return cl.RegimeOutcome("process-cold", "<raised>", str(exc), {})

    # A zero at EITHER count refuses the whole regime.
    if regime(0, 0, 0).outcome != "P5":
        problems.append("A=0 at both counts did not refuse")
    if regime(0, 1, 4, a15=1, b15=1, c15=4).outcome != "P5":
        problems.append("A=0 at n=5 alone did not refuse the regime")
    if regime(1, 1, 4, a15=0, b15=1, c15=4).outcome != "P5":
        problems.append("A=0 at n=15 alone did not refuse the regime")

    # B == 0 with a live A is a clean P2 and must survive. Routing it to P5
    # would discard one of the cleanest results the round can produce.
    r = regime(1, 0, 4)
    if r.outcome != "P2":
        problems.append(f"A=1, B=0, C=4 classified {r.outcome}, not P2: the padded arm "
                        "shows no excess and the real binary does, which is exactly "
                        "what P2 means")

    # No epsilon. A tiny but non-zero A must classify, not refuse: a tolerance
    # here would be an absolute threshold with no preregistered basis.
    tiny = regime(Fraction(1, 10 ** 9), 0, 4)
    if tiny.outcome == "P5" and "exactly 0" in tiny.why:
        problems.append("a tiny but NON-ZERO A was refused by the zero guard; the guard "
                        "is exact zero, and an epsilon would be a new threshold")

    # And the guard must say why, not merely refuse.
    if "multiplicative reference" not in regime(0, 0, 0).why:
        problems.append("the zero-A refusal does not state its reason")

    if problems:
        fail("round7-zero-guard", "; ".join(problems))
    else:
        ok("round7-zero-guard", "A=0 at either repetition count refuses the regime with "
                                "a stated reason; B=0 with a live A still classifies "
                                "(A=1,B=0,C=4 -> P2); a non-zero A is never refused")


def control_boundaries() -> None:
    """Each rule's exact edge lands where it was ratified, not one step away."""
    problems = []
    F = Fraction
    cases = [
        # (A, B, C, expected, what the edge is)
        (2, 0, 3, "P4", "C = 1.5A exactly is P4: the inequality is <=, and P1 needs >"),
        (2, 6, 5, "P1", "C above 1.5A, B = 3A, and C inside [2/3B, 1.5B] = [4, 9]"),
        (1, 3, 2, "P1", "C = (2/3)B exactly is inside P1's band"),
        (1, 3, F(9, 2), "P1", "C = 1.5B exactly is inside P1's band"),
        (1, 3, 6, "P3", "C = 2B exactly is P3, and 6 > 1.5*3 puts it outside P1's band"),
        (2, 3, 6, "P2", "B = 1.5A exactly and C = 3A exactly is P2"),
        (2, 3, F(59, 10), "P5", "B = 1.5A exactly but C just under 3A fires nothing"),
        (1, 3, 5, "P5", "B = 3A but C sits above 1.5B and below 2B: no rule covers it"),
    ]
    for a, b, c, want, why in cases:
        try:
            got = cl.outcome_at(a, b, c)
        except cl.ClassifierError as exc:
            problems.append(f"A={a}, B={b}, C={c} raised {exc}")
            continue
        if got != want:
            problems.append(f"A={a}, B={b}, C={c} -> {got}, want {want} ({why})")

    # Inputs that are not measurements are refused rather than classified. A
    # non-finite drift falling through to P5 would read as a considered verdict.
    for bad, label in ((float("nan"), "NaN"), (float("inf"), "infinity"),
                       (-1, "a negative drift"), (True, "a boolean")):
        try:
            cl.outcome_at(1, 1, bad)
        except cl.ClassifierError:
            pass
        else:
            problems.append(f"{label} was classified rather than refused")

    if problems:
        fail("round7-boundaries", "; ".join(problems))
    else:
        ok("round7-boundaries", f"{len(cases)} ratified edges land where the rules put "
                                "them, and a non-finite, negative or boolean drift is "
                                "refused rather than classified")


def control_regime_reading() -> None:
    """Disagreement between counts is P5; disagreement between regimes is not."""
    problems = []
    cold = {5: (1, 0, 4), 15: (1, 0, 4)}          # P2 at both counts
    warm = {5: (1, 0, 1), 15: (1, 0, 1)}          # P4 at both counts

    r = cl.regime_outcome("process-cold", {5: (1, 0, 4), 15: (1, 0, 1)})
    if r.outcome != "P5":
        problems.append(f"n=5 P2 and n=15 P4 classified {r.outcome}, not P5")
    elif "n=5" not in r.why or "n=15" not in r.why:
        problems.append("the count-disagreement refusal does not name both counts")

    read = cl.read_round({"process-cold": cold, "warm": warm})
    per = read["per_regime"]
    if per["process-cold"]["outcome"] != "P2" or per["warm"]["outcome"] != "P4":
        problems.append(f"the regimes were not classified independently: {per}")
    if not read["regime_split"]:
        problems.append("a cold P2 against a warm P4 was not reported as a split")
    if "NOT" not in str(read["regime_split_reading"]):
        problems.append("the split reading does not say it is not P5 — the owner ruled a "
                        "split is a cache-sensitivity signal, and collapsing it into "
                        "inconclusive discards the round's most informative result")
    same = cl.read_round({"process-cold": cold, "warm": cold})
    if same["regime_split"]:
        problems.append("two identical regimes were reported as a split")

    # Only the ratified counts. n=25 is not a knob this round may reach for.
    for bad in ({5: (1, 1, 1)}, {5: (1, 1, 1), 25: (1, 1, 1)},
                {5: (1, 1, 1), 15: (1, 1, 1), 25: (1, 1, 1)}):
        try:
            cl.regime_outcome("process-cold", bad)
        except cl.ClassifierError:
            pass
        else:
            problems.append(f"repetition counts {sorted(bad)} were accepted")

    if problems:
        fail("round7-regime-reading", "; ".join(problems))
    else:
        ok("round7-regime-reading", "n=5 against n=15 within a regime is P5; cold "
                                    "against warm is reported as a split and not "
                                    "collapsed; only n in {5,15} is accepted")


# --- the structural preflight ----------------------------------------------


_DAMAGE = {
    "padding dropped by the linker": ("""#include <stdint.h>
const uint64_t own_round7_padding[200000] = { 1 };
""", ("-fdata-sections",), ("-Wl,--gc-sections",), "B1"),
    "padding present but never mapped": ("""__asm__(".section .own_round7_note,\\"\\",@progbits\\n"
        ".globl own_round7_padding\\n"
        ".type own_round7_padding,@object\\n"
        "own_round7_padding:\\n"
        ".fill 1600000, 1, 0\\n"
        ".size own_round7_padding, 1600000\\n"
        ".previous\\n");
""", (), (), "B2"),
    "padding sized nothing like arm C": ("""#include <stdint.h>
const volatile uint64_t own_round7_padding[64] = { 1 };
""", (), (), "B3"),
}

_ALTERED_WORK = """#include <stdint.h>
#include <stdlib.h>
int main(int argc, char **argv) {
    if (argc < 2) return 2;
    uint64_t n = strtoull(argv[1], NULL, 10);
    volatile uint64_t x = 1;
    for (uint64_t i = 0; i < n; i++) {
        x = x * 1103515247ull + 12345ull;   /* one constant changed */
    }
    return (x == 0xFFFFFFFFFFFFFFFFull) ? 1 : 0;
}
"""


def control_preflight() -> None:
    """B1-B4 pass on healthy arms, and each refuses the damage it owns.

    The damage is BUILT, not simulated: a real linker really does drop an
    unreferenced non-volatile constant under --gc-sections, and a section
    emitted with empty flags really is absent from every PT_LOAD. A fixture
    that merely edited a dictionary would prove the checks can read a
    dictionary.
    """
    if sys.platform != "linux" or shutil.which("gcc") is None:
        ok("round7-preflight", f"skipped on {sys.platform}: the arms are ELF binaries "
                               "built with gcc, and Round 7 is a Linux round. Nothing "
                               "is claimed about this platform")
        return
    candidate = ROOT / "rust/target/release/own-cli"
    problems = []
    with tempfile.TemporaryDirectory(prefix="round7-pre-") as td:
        tmp = Path(td)

        # (1) The healthy arms.
        if candidate.is_file():
            record = pf.preflight(candidate, tmp / "healthy")
            for name, res in record["checks"].items():
                if not res["pass"]:
                    problems.append(f"{name} failed on healthy arms: {res['why']}")
            if record["checks"]["B4"]["test"] not in ("raw-bytes",
                                                      "address-stripped-disassembly"):
                problems.append("B4 did not name which test decided")
        else:
            ok("round7-preflight", "arm C (rust/target/release/own-cli) is not built "
                                   "here, so the healthy pass and B3 were not exercised")
            return

        # (2) Each damage, refused by the check that owns it.
        work_obj = tmp / "spin.o"
        _gcc(["-O2", "-c", "-o", str(work_obj), str(pf.WORK_SOURCE)], problems)
        arm_a = tmp / "arm-a"
        _gcc(["-O2", "-o", str(arm_a), str(work_obj)], problems)
        arm_c = Elf64(candidate)

        for label, (source, cflags, ldflags, owner) in _DAMAGE.items():
            src = tmp / f"{owner}.c"
            src.write_text(source, encoding="utf-8")
            obj, binary = tmp / f"{owner}.o", tmp / f"arm-b-{owner}"
            _gcc(["-O2", *cflags, "-c", "-o", str(obj), str(src)], problems)
            _gcc(["-O2", *ldflags, "-o", str(binary), str(work_obj), str(obj)], problems)
            if not binary.is_file():
                problems.append(f"{label}: the damaged arm did not build")
                continue
            bad = Elf64(binary)
            results = {"B1": pf.check_b1(bad), "B2": pf.check_b2(bad),
                       "B3": pf.check_b3(bad, arm_c), "B4": pf.check_b4(Elf64(arm_a), bad)}
            if results[owner]["pass"]:
                problems.append(f"{label}: {owner} accepted it — {results[owner]['why']}")

        # (3) Altered work, refused by B4 and by nothing else.
        alt = tmp / "altered.c"
        alt.write_text(_ALTERED_WORK, encoding="utf-8")
        alt_obj, alt_bin = tmp / "altered.o", tmp / "arm-b-altered"
        _gcc(["-O2", "-c", "-o", str(alt_obj), str(alt)], problems)
        pad_obj = tmp / "healthy" / "pad.o"
        if pad_obj.is_file():
            _gcc(["-O2", "-o", str(alt_bin), str(alt_obj), str(pad_obj)], problems)
            if alt_bin.is_file():
                res = pf.check_b4(Elf64(arm_a), Elf64(alt_bin))
                if res["pass"]:
                    problems.append("B4 accepted an arm whose work loop uses a different "
                                    "constant — the one thing it exists to refuse")
        else:
            problems.append("the healthy pad object was not kept, so the altered-work "
                            "arm could not be linked against it")

    if problems:
        fail("round7-preflight", "; ".join(problems))
    else:
        ok("round7-preflight", "B1-B4 pass on freshly built arms, and a dropped, "
                               "unmapped, mis-sized or work-altered arm B is each "
                               "refused by the check that owns it")


def _gcc(args: list[str], problems: list[str]) -> None:
    r = subprocess.run(["gcc", *args], capture_output=True)
    if r.returncode != 0:
        problems.append(f"gcc {' '.join(args)} failed: "
                        + r.stderr.decode("utf-8", "replace")[:200])


def run() -> int:
    control_outcome_exclusivity()
    control_zero_guard()
    control_boundaries()
    control_regime_reading()
    control_preflight()
    print()
    print(f"round 7 apparatus controls: {len(_PASSES)} passed, {len(_FAILURES)} failed")
    return 1 if _FAILURES else 0


if __name__ == "__main__":
    sys.exit(run())
