# Round 6 — variance characterisation: preregistration

**Status:** written and committed BEFORE any Round 6 measurement exists.
**Authorised at:** exact head `0374793c9aa0b9ad9b0e55013d125338ae8b0d42`, whose
CI completed success on both the push and pull_request runs, head unchanged.
**Tag:** `CALIBRATION_ONLY`. This round produces no decisive number, no
threshold, no budget, and no D7 freeze.

This document exists so that the analysis is fixed before the data. Everything
below — what is measured, how, how many times, and which conclusion each
possible shape licenses — is decided now. A characterisation whose analysis is
chosen after seeing the numbers is a threshold hunt with better manners.

## The question

Six sizing attempts have produced three `n=5` failures and two `n=15` failures.
Every cell that has ever fallen outside the 0.35 policy is a `rust` cell with a
median under 10 ms, out of a population spanning roughly 1.8 ms to 3.2 s. Three
explanations remain indistinguishable from the evidence to date:

1. **A measurement-scale effect.** Below some duration, run-to-run variation is
   dominated by fixed costs — process spawn, scheduling, page faults — so a
   *relative* tolerance necessarily bites hardest at the short end, whatever is
   being measured.
2. **Something specific to the Rust invocations**, which happen to be the short
   cells.
3. **Between-session environmental variation**, which would move everything and
   merely shows first where the relative denominator is smallest.

Round 6 separates (1) from (2) and (3) by measuring something that is neither
Rust nor Python product code, across durations that span the region of interest.

## What is measured

A **synthetic deterministic helper**, run in a **fresh process** per iteration,
at eight target durations:

    1, 2, 4, 8, 16, 32, 64, 128 ms

The helper is not Rust and not Python product code, does no I/O, and computes a
fixed, deterministic amount of work. Its per-scale iteration count is fixed by a
**one-off setup pass** whose numbers are recorded in this document before the
measurement pass runs, and is then never re-derived. A helper that re-calibrates
itself each run is measuring a moving target.

Fixed in advance, per scale:

| | |
|---|---|
| repetitions | `n` in {5, 15} — the same two counts the instrument permits, and no others |
| warmup | 2, the instrument's policy default, unchanged |
| independent A/B sessions | **5** per (scale, n); one session is a run A and a run B |

That is 8 scales x 2 counts x 5 sessions x 2 halves = 160 measurement runs.

## What is recorded, per cell

- absolute median shift `|median_B - median_A|`
- relative median shift `|median_B - median_A| / median_A`
- MAD and IQR of each half
- **every raw observation**, not just the summary
- scheduler metadata; on Linux, CPU affinity and a context-switch signal

**No pass/fail tolerance is computed, applied, or reported.** There is no
verdict in this round. `0.35` is not consulted, and nothing in this round may
move it.

## Predeclared outcomes, and what each licenses

| shape | reading | what it licenses |
|---|---|---|
| **O1** absolute drift roughly constant across the ladder while relative shift grows as duration falls | the instability is a measurement-scale effect, present in code that has nothing to do with either engine | a v2 envelope of the form `|delta| <= A + R*t` **may be designed**, with `A` and `R` estimated from **this metrology dataset only** |
| **O2** the ladder is stable at 2–8 ms while real Rust invocations keep wandering | the instability is *not* a duration-scale artifact | an absolute floor **must NOT** be introduced; the cause is elsewhere and Round 6 has not found it |
| **O3** neither shape appears cleanly | inconclusive | report it as inconclusive and stop |

Naming O3 in advance matters: without it, an ambiguous dataset gets read as
whichever of O1 or O2 the reader was hoping for.

## Explicitly forbidden in this round

- Deriving `A` or `R` — or any other constant — from the Owen cells. The
  metrology dataset is the only permitted source, and only under O1.
- Using `0.508`, or any other observed failing value, as or toward a threshold.
  The owner's ruling stands: a v2 envelope and a fitted acceptance bound are two
  different statistical professions, however much the numbers enjoy dressing up
  as each other.
- Introducing an absolute noise floor under O2.
- Choosing `T_min`, `N_min` or `N_max`.
- Moving `0.35`, `--warmup`, or trying any repetition count other than 5 and 15.
- Any decisive workload, any decisive timing, any resource exposure of decisive
  work, any D7 threshold or budget, any C1/C2 freeze, any #263-B, any Stage 3.

## What may be used as input

The existing calibration history may be read as calibration evidence. This is
not forbidden peeking: frozen #263-A permits calibration variance as an input to
sizing the instrument, and the owner has ratified that reading. In particular
the observation that all five historical failures sit on `rust` cells under
10 ms may be investigated. What may not happen is that observation becoming a
number in a D7 acceptance rule.

## Stop rules

- If the setup pass cannot produce stable per-scale iteration counts, stop and
  report; do not proceed with a helper whose duration is not fixed.
- If the measurement pass cannot complete a full session for any (scale, n),
  report the gap rather than substituting a partial session.
- On O2 or O3, stop after reporting. Neither licenses a change to any policy.

## Deliverables

- The setup pass's per-scale iteration counts, recorded in this document.
- A committed metrology dataset with every raw observation.
- A written reading against O1/O2/O3, decided by the table above rather than by
  what would be convenient.

## Amendment 1 — the helper is compiled, recorded before any measurement

Made after the plan was committed and **before any measurement pass ran**, for a
reason the plan should have anticipated and did not.

The instrument's timed interval includes **process spawn**. Measured on this
machine:

| | median |
|---|---|
| `python3 -c pass` | 11.8 ms |
| `/bin/true` | 1.14 ms |

A Python helper therefore cannot reach the 1, 2, 4 or 8 ms rungs at all — its
floor sits above half the ladder. The helper is consequently written in **C**
(`scripts/round6/spin.c`), compiled once with `-O2`, and identified by the
sha256 of the resulting binary, which the measurement pass re-checks against the
setup pass. C is neither Rust nor Python product code, so the exclusion the
owner ratified is unaffected.

**The 1 ms rung sits at or below the spawn floor** (~1.25 ms for the compiled
helper). It is kept rather than dropped, and the setup pass marks it
`at_or_below_spawn_floor`. That is a datum, not a defect: it bounds what any
*relative* tolerance can possibly mean at that scale, which is close to the
question this round is asking.

Timing goes through `perf_baseline.Harness._run_once` — the instrument's own
interval, `perf_counter_ns` around `Popen` and `wait4` — rather than a
re-implementation. Round 6 exists to characterise that interval, and a lookalike
would characterise a different one while the resemblance did the arguing. No
workload is ever passed to the firewall, and no decisive workload appears
anywhere in this round.

## Per-scale iteration counts (setup pass)

Filled by the setup pass at `8c61a7b`, before the measurement pass ran.
Helper `f937b36bd4da`, spawn floor **1.332 ms**,
689,052 iterations per ms. Recorded in
`docs/evidence/round6/p022-263a-round6-scales.linux.json`, which lives in a
subdirectory so it is outside the flat report-of-record glob by construction and
not merely by key shape.

| target ms | iterations | achieved median ms |
|---|---|---|
| 1 | 0 | 1.448 _(at/below spawn floor)_ |
| 2 | 460,280 | 2.0128 |
| 4 | 1,838,383 | 4.09 |
| 8 | 4,594,589 | 8.499 |
| 16 | 10,107,001 | 16.4963 |
| 32 | 21,131,826 | 31.6907 |
| 64 | 43,181,474 | 63.3262 |
| 128 | 87,280,771 | 127.3134 |

The ladder tracks its targets from 2 ms up. The 1 ms rung is the spawn floor and
is kept, flagged, and read as a bound rather than a duration.
