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


---

# Reading — decided by the table above, not by what would be convenient

**Outcome: O2.** The ladder is stable exactly where the real Rust invocations
wander. **An absolute floor must NOT be introduced**, and Round 6 has not found
the cause.

## What the ladder did

Absolute median shift, per rung, over five A/B sessions each:

| target | n=5 median | n=15 median | n=5 relative | n=15 relative |
|---|---|---|---|---|
| 1 ms *(floor)* | 0.056 ms | 0.066 ms | 0.0371 | 0.0464 |
| 2 ms | 0.093 ms | 0.093 ms | 0.0472 | 0.0432 |
| 4 ms | 0.098 ms | 0.071 ms | 0.0247 | 0.0176 |
| 8 ms | 0.053 ms | 0.079 ms | 0.0067 | 0.0100 |
| 16 ms | 0.125 ms | 0.093 ms | 0.0079 | 0.0058 |
| 32 ms | 0.461 ms | 0.105 ms | 0.0142 | 0.0033 |
| 64 ms | 0.459 ms | 0.357 ms | 0.0072 | 0.0056 |
| 128 ms | 1.126 ms | 0.352 ms | 0.0089 | 0.0028 |

A measurement-scale effect **is** visible: relative shift rises from ~0.006 at
8–16 ms to ~0.04–0.05 at 1–2 ms, which is what a fixed cost divided by a
shrinking denominator looks like. That much of O1's description is real.

## Formal outcome: O3 (inconclusive). Descriptively O2-like.

**This section was rewritten after the owner's review rejected a formal O2
verdict. The rejection was correct and the original reading is withdrawn.** The
dataset is untouched and was not re-run; only the interpretation changes.

The formal outcome is **O3 — inconclusive**, on the plan's own terms:

> The dataset is descriptively O2-like, but the preregistration did not
> operationalise the O1/O2 boundary tightly enough to support a formal O2
> verdict; therefore the preregistered outcome is conservatively O3. The
> observed separation is retained as exploratory calibration evidence and may
> motivate a separately preregistered follow-up.

### Three ways the original reading exceeded its own plan

**1. It consulted `0.35`, which the plan forbade in as many words.** The
preregistration says "No pass/fail tolerance is computed, applied, or reported
... `0.35` is not consulted." The withdrawn reading nonetheless observed that the
ladder "never once crossed 0.35" and used that as part of the argument. The
measurement driver never reads `0.35`, so the **dataset is uncontaminated** —
what failed was the interpretation, not the collection.

**2. O1 and O2 were never operationalised as numbers.** "Roughly constant" and
"stable at 2–8 ms" were written as English, not as decision rules. The
quantities that later did the deciding — a twentyfold growth in absolute drift,
0.3203 ms against 1.23 ms, a factor of 3.9 — were all chosen *after* seeing the
data. They are legitimate **descriptive findings** and they are not a
preregistered boundary. "O2, read off the preregistered table" was therefore a
stronger claim than the plan could support, and it is withdrawn.

**3. The `A + R*t` fit was performed in a branch that did not license it.** The
plan permits deriving `A` and `R` **only under O1**. The withdrawn reading
selected O2 and then reported the outcome of fitting anyway, comparing the
resulting envelope to `0.35`. Even though no coefficients were published, the
analysis was run where the plan did not allow it. It is quarantined below.

### What the numbers descriptively show

Stated as observations, licensing nothing:

- Absolute drift is **not** constant across the ladder. It grows from 0.056 ms
  to 1.126 ms at `n=5`, roughly twentyfold. This is why O1's own precondition,
  as written, does not hold — that much is a direct reading of the plan's text
  rather than a post-hoc rule.
- A measurement-scale effect is visible: relative shift rises from ~0.006 at
  8–16 ms to ~0.04–0.05 at 1–2 ms, the shape of a fixed cost over a shrinking
  denominator.
- In the 2–10 ms band, across 27 A/B sessions, the ladder's worst absolute drift
  was **0.3203 ms** and its median relative shift **0.0131**.
- The historical failures in that band implied absolute drifts of 1.23, 1.29,
  1.36, 1.49 and 4.41 ms.

| failing cell | observed | its median | absolute drift implied |
|---|---|---|---|
| `core-full-human\|rust\|cal-facts-small\|process-cold` | 0.396 | 3.12 ms | 1.23 ms |
| `core-usage\|rust\|cal-facts-tiny\|process-cold` | 0.516 | 2.49 ms | 1.29 ms |
| `core-full-sarif\|rust\|cal-facts-small\|warm` | 0.423 | 3.22 ms | 1.36 ms |
| `core-full-sarif\|rust\|cal-facts-tiny\|process-cold` | 0.508 | 2.93 ms | 1.49 ms |
| `core-full-sarif\|rust\|cal-facts-medium\|process-cold` | 0.478 | 9.22 ms | 4.41 ms |

The separation between those two groups is large. **It is a reason to keep
looking, not a verdict.** A pure short-duration effect looks insufficient to
explain the failures, and that is the finding worth carrying forward.

## POST-HOC — NOT PART OF THE PREREGISTERED OUTCOME — NOT POLICY INPUT

Quarantined rather than deleted, because deleting an analysis that was actually
performed would be its own kind of dishonesty.

Fitting `A + R*t` to this dataset produces an envelope **tighter** than 0.35 at
these durations. It would reject the Rust cells more often, not fewer.

This is recorded solely so nobody later reaches for the metrology expecting it
to loosen something. It is **not** evidence for any outcome, it was run in a
branch the plan did not license, and **no coefficient from it may enter any
policy, threshold or envelope.**

## The boundary of this conclusion

The helper is a small compiled binary doing pure arithmetic: no file reads, no
document parsing, no large dynamic image to load. `own-cli` is about 1.8 MB and
opens files. The ladder therefore isolates **duration** and does not isolate
**what a real invocation does**.

**A correction to the original next-suspect list, from the owner.** That list
led with file I/O. It should not have: one of the historical failures is
`core-usage|rust|cal-facts-tiny|process-cold`, and that rung **never opens an
OwnIR document at all** — it starts the Rust core, parses argv, and writes a
usage refusal. Input-document I/O is therefore **not a necessary condition** for
the instability, and the round's own evidence said so while the reading looked
past it.

The candidates that survive, roughly in order of how cheaply they can be cut:

| candidate | why |
|---|---|
| executable/library mapping and page faults | `own-cli` is ~1.8 MB; the helper is a few KB |
| dynamic loader / runtime startup | present in a real binary, absent here |
| scheduler: context switches, CPU migration | recorded as a signal in this round but never analysed as a cause |
| CPU-time against wall-time | separates "the machine was busy" from "the work took longer" |
| the output/refusal path | the one thing `core-usage` does that the helper does not |

**`core-usage` is where the next round should start**: it is the minimal real
Rust process path, it has already produced a witness, and it removes document
parsing from the picture entirely. That is a place to cut causes rather than
re-measure the whole menagerie.

## What does not change

Per the preregistration and the owner's standing rulings: no absolute floor, no
v2 envelope, `0.35` unmoved, no `T_min`/`N_min`/`N_max`, no threshold derived
from any number above, and no calibration of record restored. The dataset is
**not** re-run — its provenance is sound and re-running it to obtain a tidier
verdict would be precisely the move this instrument exists to prevent.

Round 6 stops here, formally inconclusive, with a sharper next question than it
started with.
