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
    round7-schedule             the execution order is blocked, seeded, and replayable
    round7-execution-contract   plan mode starts no clock; the timed bytes are the preflighted ones
    round7-outcome-contract     every spawn, warmups included, did the work its arm exists to do

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

import json
import shutil
import subprocess
import sys
import tempfile
from fractions import Fraction
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "round7"))
sys.path.insert(0, str(ROOT / "scripts"))

import classify as cl  # noqa: E402
import perf_baseline as pb  # noqa: E402
import preflight as pf  # noqa: E402
import runner as rn  # noqa: E402
import schedule as sch  # noqa: E402
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


# --- the execution contract ------------------------------------------------


def control_schedule() -> None:
    """The order arms run in is fixed before the data, and replayable after it.

    The preregistration fixed how many sessions and halves and said nothing
    about order. Run every A, then every B, then every C, and machine drift
    becomes "the effect of the real binary" -- a result that would survive every
    other check in this PR.
    """
    problems = []
    blocks = sch.blocks()
    halves = sch.planned_halves()

    # (1) The design, counted rather than described.
    want_blocks = len(sch.REGIMES) * len(sch.REPETITION_COUNTS) * sch.SESSIONS
    if len(blocks) != want_blocks:
        problems.append(f"{len(blocks)} blocks, want {want_blocks} (2 regimes x 2 counts "
                        f"x {sch.SESSIONS} sessions)")
    if len(halves) != want_blocks * 6:
        problems.append(f"{len(halves)} halves, want {want_blocks * 6}")
    cells = [b.key for b in blocks]
    if len(set(cells)) != len(cells):
        problems.append("a (regime, n, session) cell appears twice in the schedule")
    expected_cells = {f"{r}|n{n}|s{s}" for r in sch.REGIMES
                      for n in sch.REPETITION_COUNTS for s in range(1, sch.SESSIONS + 1)}
    if set(cells) != expected_cells:
        problems.append(f"the schedule does not cover the design: missing "
                        f"{sorted(expected_cells - set(cells))[:3]}")

    # (2) Every block runs all three arms, with each arm's halves ADJACENT.
    for b in blocks:
        if sorted(b.arm_order) != sorted(sch.ARMS):
            problems.append(f"block {b.key} runs {b.arm_order}, not all three arms")
            break
        seq = [(h.arm, h.half) for h in b.halves]
        for i in range(0, len(seq), 2):
            if seq[i][1] != "first" or seq[i + 1][1] != "second" or seq[i][0] != seq[i + 1][0]:
                problems.append(f"block {b.key} splits an arm's halves: {seq}")
                break

    # (3) Shuffled, not merely claimed to be. A constant arm order, or a block
    # order equal to the generated order, would satisfy every check above.
    if len({b.arm_order for b in blocks}) < 2:
        problems.append(f"every block uses the same arm order {blocks[0].arm_order}: "
                        "the within-block shuffle is doing nothing, and drift would "
                        "align with arms exactly as if nothing were shuffled")
    generated = [f"{r}|n{n}|s{s}" for r in sch.REGIMES
                 for n in sch.REPETITION_COUNTS for s in range(1, sch.SESSIONS + 1)]
    if cells == generated:
        problems.append("the block order is the generation order; the outer shuffle is "
                        "doing nothing and all of process-cold would run before all warm")

    # (4) Deterministic, and sensitive to the seed. A schedule nobody can replay
    # is a fond memory; one that ignores its seed is not randomised at all.
    if [b.key for b in sch.blocks()] != cells:
        problems.append("two calls with the same seed produced different orders")
    other = [b.key for b in sch.blocks(seed=sch.SCHEDULE_SEED ^ 0xFFFF)]
    if other == cells:
        problems.append("a different seed produced an identical order; the seed is "
                        "decorative")

    # (5) The seed is the Round 6 helper's, not a number I chose. Checked
    # against the committed artifact rather than against the comment claiming it.
    scales = json.loads((ROOT / "docs/evidence/round6/p022-263a-round6-scales.linux.json")
                        .read_text(encoding="utf-8"))
    want_seed = int(scales["helper_sha256"][:16], 16)
    if sch.SCHEDULE_SEED != want_seed:
        problems.append(f"the seed 0x{sch.SCHEDULE_SEED:016x} is not the Round 6 helper's "
                        f"0x{want_seed:016x}: it is a number someone picked, and nothing "
                        "stops it being re-picked until the order looks tidy")

    # (6) The spawn count is computed from the plan, not quoted from prose.
    spawns = sch.process_spawns(warmup_discards=2)
    if spawns != 2640:
        problems.append(f"the plan spawns {spawns} processes; the preregistration says "
                        "2640, and a quoted number nothing computes is one that drifts")

    if problems:
        fail("round7-schedule", "; ".join(problems))
    else:
        ok("round7-schedule", f"{len(blocks)} blocks x 6 halves = {len(halves)}, every "
                              f"(regime, n, session) exactly once, each arm's halves "
                              f"adjacent, {len({b.arm_order for b in blocks})} distinct arm "
                              f"orders, replayable from the seed and different without it; "
                              f"{spawns} planned spawns computed from the plan")


def control_execution_contract() -> None:
    """Plan mode starts no clock, and the timed bytes are the preflighted bytes."""
    problems = []

    # (1) The work binding reads Round 6's ladder rather than remembering it.
    binding = rn.bind_work()
    if binding.iterations != 460280:
        problems.append(f"the 2 ms rung binds {binding.iterations} iterations, not 460280")
    if not binding.helper_sha256:
        problems.append("the binding carries no helper sha256, so arm A cannot be checked "
                        "against the ladder that gave it its iteration count")
    # And it refuses a ladder that cannot supply one, rather than inventing a count.
    with tempfile.TemporaryDirectory(prefix="round7-bind-") as td:
        bad = Path(td) / "scales.json"
        bad.write_text(json.dumps({"helper_sha256": "x", "rungs": [{"target_ms": 4}]}),
                       encoding="utf-8")
        try:
            rn.bind_work(bad)
        except rn.ExecutionContractBreach:
            pass
        except Exception as exc:
            # Reported, not raised. A control that dies here exits non-zero with
            # no FAIL line, which reads as "caught" to a mutation runner counting
            # exit codes and as nothing at all to a human reading CI.
            problems.append(f"bind_work raised {type(exc).__name__} instead of refusing a "
                            f"ladder with no 2 ms rung: {exc}")
        else:
            problems.append("a ladder with no 2 ms rung was accepted; the arms' work would "
                            "be whatever the runner felt like")

    if sys.platform != "linux" or shutil.which("gcc") is None:
        if problems:
            fail("round7-execution-contract", "; ".join(problems))
        else:
            ok("round7-execution-contract", f"the work binding reads 460280 from Round 6's "
                                            f"ladder and refuses one without a 2 ms rung; "
                                            f"the arm-identity half needs ELF arms and is "
                                            f"skipped on {sys.platform}")
        return

    candidate = ROOT / "rust/target/release/own-cli"
    if not candidate.is_file():
        ok("round7-execution-contract", "the work binding holds; arm C is not built here, "
                                        "so the identity freeze was not exercised")
        return

    with tempfile.TemporaryDirectory(prefix="round7-exec-") as td:
        tmp = Path(td)
        # (2) Plan mode starts no clock. COUNTED, at the one function that can.
        calls = {"n": 0}
        real = rn.time_half

        def counting(*a: object, **k: object) -> dict[str, object]:
            calls["n"] += 1
            return real(*a, **k)                        # type: ignore[arg-type]

        rn.time_half = counting                         # type: ignore[assignment]
        try:
            record = rn.run(candidate, tmp / "arms", measure=False)
        finally:
            rn.time_half = real                         # type: ignore[assignment]
        if calls["n"]:
            problems.append(f"plan mode called the timing function {calls['n']} times; it "
                            "must return before the clock is reachable at all")
        if record["measurements"] is not None:
            problems.append("plan mode produced measurements")
        if record["stop_conditions"]:
            problems.append(f"plan mode stopped: {record['stop_conditions']}")

        # (3) The freeze covers all three arms with sha256 AND byte length.
        frozen = record["frozen_arms"]
        if not isinstance(frozen, dict) or set(frozen) != {"A", "B", "C"}:
            problems.append(f"the identity freeze covers {frozen} rather than all three arms")
        else:
            for role, row in frozen.items():
                if not row.get("sha256") or not row.get("file_bytes"):
                    problems.append(f"arm {role}'s freeze lacks a sha256 or a byte length")

        # (4) A byte changed after the freeze is refused. Actually changed, on
        # disk, not simulated: this is the defect the whole transaction exists
        # to prevent, and a fixture that edited a dict would prove nothing.
        prepared = rn.prepare(candidate, tmp / "arms2")
        arm_b = prepared.frozen["B"].path
        arm_b.write_bytes(arm_b.read_bytes() + b"\x00")
        try:
            rn.verify_identities(prepared.frozen, "after a deliberate tamper")
        except rn.ExecutionContractBreach as exc:
            if "changed since the freeze" not in str(exc):
                problems.append(f"the refusal does not say what happened: {exc}")
        else:
            problems.append("an arm rebuilt after the freeze was accepted for timing — the "
                            "preflight would prove properties of bytes that are gone")
        # And a deleted arm, which is the rebuild-in-a-temp-dir case exactly.
        arm_b.unlink()
        try:
            rn.verify_identities(prepared.frozen, "after a deliberate delete")
        except rn.ExecutionContractBreach:
            pass
        else:
            problems.append("a missing arm was accepted for timing")

        # (5) Arm A must BE the Round 6 helper, by sha, or the round stops.
        # Both directions: the real arm accepted, a stand-in refused by name.
        if not prepared.binding_ok:
            problems.append(f"arm A does not match the Round 6 helper: "
                            f"{prepared.binding_problem}")
        ok_, why_ = rn.check_binding("0" * 64, binding)
        if ok_:
            problems.append("a binary that is not the Round 6 helper was accepted as arm "
                            "A; 460280 iterations would then mean whatever that binary "
                            "happens to do, not 2 ms")
        elif "do not re-derive" not in why_:
            problems.append(f"the binding refusal does not forbid re-deriving a count: {why_}")

    if problems:
        fail("round7-execution-contract", "; ".join(problems))
    else:
        ok("round7-execution-contract", "plan mode calls the timing function zero times; "
                                        "the freeze carries sha256 and byte length for all "
                                        "three arms; a tampered or deleted arm is refused "
                                        "by name; and arm A is byte-identical to Round 6's "
                                        "2 ms helper")


class _FakeHarness:
    """A harness whose interval returns exit codes I choose.

    The point of the control is the CHECK, not the clock: driving real processes
    to exit 127 on demand would test the operating system. This returns rows
    shaped exactly like `_run_once`'s so the check sees what it would really see.
    """

    def __init__(self, codes: list[int]) -> None:
        self.codes = list(codes)
        self.spawns = 0

    def _run_once(self, argv: list[str], env: dict[str, str],
                  cwd: Path) -> dict[str, object]:
        rc = self.codes[self.spawns] if self.spawns < len(self.codes) else 0
        self.spawns += 1
        return {"elapsed_ns": 1_000_000, "rc": rc, "peak_rss_bytes": 1024,
                "rss_unavailable_reason": "", "accounting_unavailable_reason": ""}


def control_outcome_contract() -> None:
    """A timed process must have done the work, and warmups count too.

    This is the Round 2 defect at one remove. Twelve cells once timed
    `command-not-found` accurately and reproducibly, and the frozen instrument
    grew an outcome layer because of it. Round 7 called `_run_once` directly and
    walked straight past that layer: three perfectly identity-bound binaries
    could have measured the wrong path with great precision.
    """
    problems = []
    half = sch.Half("warm", 5, 1, "C", "first")
    argv, env, cwd = ["x"], {}, ROOT

    # (1) The healthy direction: all spawns conforming, warmups included.
    #     Wrapped, because a mutation that changes arm C's expected code makes
    #     this raise, and a control that dies here exits non-zero with no FAIL
    #     line — which reads as "caught" to anything counting exit codes and as
    #     nothing at all to a human. That ghost has a season pass by now.
    good = _FakeHarness([2] * 7)
    try:
        row = rn.time_half(good, half, argv, env, cwd, repetitions=5, discards=2)
    except rn.OutcomeContractBreach as exc:
        fail("round7-outcome-contract",
             f"a healthy arm C half (every spawn exiting 2) was refused: {exc}")
        return
    if good.spawns != 7:
        problems.append(f"{good.spawns} spawns for n=5 with 2 discards, want 7")
    if len(row["samples"]) != 5:
        problems.append(f"{len(row['samples'])} samples kept, want 5 (discards must not "
                        "be counted as measurements)")
    if row.get("expected_rc") != 2:
        problems.append("the half does not record which exit code it required")

    # (2) A stray SAMPLE is refused, and named.
    for bad_rc in (1, 127):
        h = _FakeHarness([2, 2, 2, bad_rc, 2, 2, 2])
        try:
            rn.time_half(h, half, argv, env, cwd, repetitions=5, discards=2)
        except rn.OutcomeContractBreach as exc:
            s0 = exc.strays[0]
            if s0["kind"] != "sample" or s0["observed_rc"] != bad_rc:
                problems.append(f"a sample exiting {bad_rc} was recorded as {s0}")
            for field in ("block", "arm", "half", "kind", "index", "observed_rc"):
                if field not in s0:
                    problems.append(f"the stray record omits {field!r}: "
                                    "'something exited wrong somewhere' is not a record")
        else:
            problems.append(f"arm C exiting {bad_rc} was accepted as a calibration "
                            "sample — exactly the shape that timed 12 "
                            "command-not-found cells and called them reproduced")

    # (3) A stray WARMUP is refused too. Its numbers are discarded; the evidence
    #     that the process is broken is not.
    h = _FakeHarness([2, 127, 2, 2, 2, 2, 2])
    try:
        rn.time_half(h, half, argv, env, cwd, repetitions=5, discards=2)
    except rn.OutcomeContractBreach as exc:
        if exc.strays[0]["kind"] != "warmup" or exc.strays[0]["index"] != 1:
            problems.append(f"the failing warmup was misrecorded: {exc.strays[0]}")
    else:
        problems.append("a warmup discard that failed was ignored; a discarded iteration "
                        "still proves the process is broken")

    # (4) The arms expect DIFFERENT codes, so a check keyed on one constant is
    #     wrong for two of the three. A/B must exit 0, C must exit 2.
    if rn.EXPECTED_RC != {"A": 0, "B": 0, "C": 2}:
        problems.append(f"the arms' expected exit codes are {rn.EXPECTED_RC}")
    for arm, good_rc, bad_rc in (("A", 0, 2), ("B", 0, 1), ("C", 2, 0)):
        hh = sch.Half("process-cold", 5, 1, arm, "second")
        ok_h = _FakeHarness([good_rc] * 5)
        try:
            rn.time_half(ok_h, hh, argv, env, cwd, repetitions=5, discards=0)
        except rn.OutcomeContractBreach as exc:
            problems.append(f"arm {arm} exiting {good_rc} was refused: {exc}")
        except Exception as exc:
            problems.append(f"arm {arm} exiting {good_rc} raised "
                            f"{type(exc).__name__}: {exc}")
        bad_h = _FakeHarness([bad_rc] * 5)
        try:
            rn.time_half(bad_h, hh, argv, env, cwd, repetitions=5, discards=0)
        except rn.OutcomeContractBreach:
            pass
        else:
            problems.append(f"arm {arm} exiting {bad_rc} was accepted; {arm} must exit "
                            f"{good_rc}")

    # (5) Arm C's untimed contract is the INSTRUMENT's, not a third restatement.
    if sys.platform == "linux" and shutil.which("gcc"):
        candidate = ROOT / "rust/target/release/own-cli"
        if candidate.is_file():
            with tempfile.TemporaryDirectory(prefix="round7-oc-") as td:
                prepared = rn.prepare(candidate, Path(td) / "arms")
                pre = prepared.outcome
                if not pre.ran or not pre.all_passed:
                    problems.append(f"the untimed outcome preflight refused a healthy "
                                    f"build: {pre.failed} "
                                    f"{[pre.arms[a].why for a in pre.failed]}")
                elif "core-usage" not in pre.arms["C"].contract:
                    problems.append(f"arm C is not verified through the instrument's own "
                                    f"rung: {pre.arms['C'].contract}")

                # A stand-in that exits 2 and prints NOTHING. Exit 2 is the
                # right code for the wrong reason, which is the whole argument
                # for checking evidence as well. Built, not simulated.
                stub = Path(td) / "not-really-own-cli"
                stub.write_text("#!/bin/sh\nexit 2\n", encoding="utf-8")
                stub.chmod(0o755)
                faked = {**prepared.frozen, "C": rn._identity("C", stub)}
                pre_bad = rn.outcome_preflight(faked, prepared.binding)
                if pre_bad.arms["C"].passed:
                    problems.append("a binary that exits 2 and prints nothing passed as "
                                    "arm C; the runner is reading the exit code and not "
                                    "the usage-help evidence, so any other failure "
                                    "exiting 2 would be timed as core-usage")
                elif pre_bad.all_passed:
                    problems.append("arm C failed its contract but the preflight still "
                                    "reported all_passed")

                # And a failed preflight must STOP the round, not merely be noted.
                stopped = rn.Prepared(
                    binding=prepared.binding, build=prepared.build,
                    checks=prepared.checks, preflight_failed=[],
                    frozen=prepared.frozen, binding_ok=True, binding_problem="",
                    arm_c_mapped_bytes=prepared.arm_c_mapped_bytes, outcome=pre_bad)
                if not stopped.stop_conditions:
                    problems.append("a refused outcome preflight produced no stop "
                                    "condition; the round would time the arms anyway")
                elif not any("C" in c for c in stopped.stop_conditions):
                    problems.append(f"the stop condition does not name the refused arm: "
                                    f"{stopped.stop_conditions}")
                # And exit 2 alone must NOT be enough: the usage-help contract
                # also requires stdout to name the subcommand and stderr empty.
                bad_out = pb._evidence_problem("usage-help", "", "")
                bad_err = pb._evidence_problem("usage-help", "ownir", "boom")
                if not bad_out:
                    problems.append("the usage-help contract accepts empty stdout, so a "
                                    "different failure exiting 2 would pass as arm C")
                if not bad_err:
                    problems.append("the usage-help contract accepts a non-empty stderr")
                if pb._evidence_problem("usage-help", "ownir usage", ""):
                    problems.append("the usage-help contract refuses a healthy refusal")
        # If arm C is not built here the untimed half simply does not run; the
        # rc checks above are platform-independent and already did.

    if problems:
        fail("round7-outcome-contract", "; ".join(problems))
    else:
        ok("round7-outcome-contract", "every spawn is checked against its arm's exit code "
                                      "(A/B 0, C 2), warmup discards included; a stray "
                                      "sample or warmup is refused and recorded with arm, "
                                      "block, half, kind and index; and arm C's untimed "
                                      "contract is the instrument's own core-usage rung, "
                                      "where exit 2 alone is not sufficient")


def run() -> int:
    control_outcome_exclusivity()
    control_zero_guard()
    control_boundaries()
    control_regime_reading()
    control_preflight()
    control_schedule()
    control_execution_contract()
    control_outcome_contract()
    print()
    print(f"round 7 apparatus controls: {len(_PASSES)} passed, {len(_FAILURES)} failed")
    return 1 if _FAILURES else 0


if __name__ == "__main__":
    sys.exit(run())
