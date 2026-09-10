# Round 7 — what a real invocation does that a synthetic one does not

**STATUS: DRAFT. NOT AUTHORISED. NOT EXECUTED. No Round 7 measurement exists.**

Written under the owner's step 5 ("draft next variance-round preregistration,
quantitative outcome boundaries this time"). Step 6 is a separate review and
authorisation; step 7 is execution. Nothing below has been run.

**Tag:** `CALIBRATION_ONLY`. No decisive workload, no threshold, no budget, no
D7 freeze. `0.35` is not consulted anywhere in this round, including in the
reading — that was Round 6's defect and it is not repeated.

## What Round 6 left

Round 6 was formally **O3, inconclusive**. Descriptively, its ladder was stable
at the durations where real `rust` cells fail: worst absolute drift 0.32 ms
across 27 A/B sessions at 2–10 ms, against 1.23–4.41 ms implied by the
historical failures. Short duration alone does not look sufficient.

The owner's correction to the follow-up: **it is not file I/O.** One of the
witnesses is `core-usage|rust|cal-facts-tiny|process-cold`, and that rung never
opens an OwnIR document — it starts the Rust core, parses argv, and writes a
usage refusal. Input-document I/O is therefore not a necessary condition.

## The question, and why `core-usage` is the right place to ask it

`core-usage` is the **minimal real Rust process path**: no document, no parse, no
analysis, no render of findings. It has already produced a witness. Everything
that distinguishes it from the Round 6 helper is a candidate, and there are few
enough of them to separate.

| | Round 6 helper | `core-usage` |
|---|---|---|
| image | ~16 KB | ~1.84 MB |
| linkage | dynamic, libc only | dynamic, PIE, `ld-linux-x86-64` |
| work | fixed arithmetic loop | argv parse, usage refusal to stderr |
| document I/O | none | **none** |

## Design: a ladder of process *shapes* at one duration

Round 6 varied duration and held shape fixed. Round 7 does the opposite.

| arm | binary | isolates |
|---|---|---|
| **A** `synth` | the Round 6 C helper, at its 2 ms rung | the known-stable baseline |
| **B** `synth-padded` | the same helper, byte-identical work, padded with an inert `.rodata` array to ≈1.84 MB | **image size, mapping and page-fault cost**, with the work held constant |
| **C** `core-usage` | `own-cli ownir` with no arguments, exit 2 | the real witness, whole |

The decomposition is the point:

- `D(C) − D(A)` — the total excess to be explained
- `D(B) − D(A)` — the part attributable to **image size and mapping**
- `D(C) − D(B)` — the part attributable to **everything else the real binary
  does**: loader symbol resolution, runtime startup, argv handling, the refusal
  write

Fixed in advance: `n` in {5, 15}, warmup 2, **10 independent A/B sessions per
(arm, n)**. That is 3 x 2 x 10 x 2 = 120 measurement runs. Ten rather than
Round 6's five because this round compares arms against each other, not a single
arm against a memory.

## What must be recorded, and the instrument change it requires

Per run, from the kernel's own per-child accounting:

`elapsed_ns`, `rc`, `ru_utime`, `ru_stime`, `ru_maxrss`, `ru_minflt`,
`ru_majflt`, `ru_nvcsw`, `ru_nivcsw`.

**`Harness._run_once` currently discards all of these except `ru_maxrss`.**
Round 7 therefore requires a source change to `scripts/perf_baseline.py` to
return the full `rusage`. That **moves the harness digest** and stales any
pair recorded before it.

This is declared here rather than discovered later: **approving this plan means
approving that source change and the re-record it implies.** If the change is
not wanted, the round cannot run as designed, because the fields that separate
the candidate causes are exactly the ones being thrown away.

## Quantitative outcome boundaries, fixed now

Round 6's failure was that "roughly constant" and "stable" were English. These
are arithmetic.

Let `D(arm, n)` be the **median across the 10 sessions** of
`|median_B − median_A|` for that arm at that repetition count.

| outcome | rule | what it licenses |
|---|---|---|
| **P1** image mapping dominates | `D(B) ≥ 3·D(A)` **and** `D(C) ≤ 1.5·D(B)` | the excess is image size and mapping; a follow-up may target the loader |
| **P2** not image mapping | `D(B) ≤ 1.5·D(A)` **and** `D(C) ≥ 3·D(A)` | the excess is in what the real binary *does*, not how big it is |
| **P3** both contribute | `D(B) ≥ 3·D(A)` **and** `D(C) ≥ 2·D(B)` | neither alone explains it |
| **P4** the witness did not reproduce | `D(C) ≤ 1.5·D(A)` | the round failed to capture the phenomenon; report and stop |
| **P5** none of the above | — | inconclusive; report and stop |

A rule must hold at **both** `n=5` and `n=15` to fire. If the two counts
disagree, the outcome is **P5**.

**Why ratios and not absolute milliseconds.** An absolute boundary would have to
come from somewhere. The only available sources are the failing Owen cells,
which are forbidden as input to any rule, or a number invented to fit, which is
worse. A ratio against a baseline arm measured in the same sessions is
self-calibrating and cannot import a threshold by accident.

### Mechanism attribution, also fixed now

Applied only to whichever arm shows elevation, and only after an outcome fires:

| attribution | rule |
|---|---|
| the work genuinely took longer | median `|Δ(utime+stime)|` ≥ `0.5 ×` median `|Δwall|` for that arm |
| scheduler | median `|Δwall|` ≥ `2 ×` median `|Δ(utime+stime)|` **and** median `|Δ(nvcsw+nivcsw)|` ≥ `2 ×` arm A's |
| page faults / mapping | median `|Δ(minflt+majflt)|` ≥ `2 ×` arm A's |

More than one may fire. None firing is itself a reportable result: it would mean
the drift is visible in wall time and in none of the accounting the kernel
offers, which is worth knowing.

## Explicitly forbidden

- Consulting, reporting or comparing against `0.35`, anywhere, including in the
  reading. This is Round 6's defect and it does not recur.
- Deriving any threshold, budget, floor or envelope from any number produced
  here.
- Using the Owen failing cells as input to any rule. They are the phenomenon
  being explained, not a calibration source.
- Choosing `T_min`, `N_min`, `N_max`, moving `--warmup`, or using any repetition
  count other than 5 and 15.
- Any decisive workload, decisive timing, resource exposure of decisive work,
  D7 threshold, C1/C2 freeze, #263-B, Stage 3 or Stage 4.
- Reporting an outcome not produced by the table above. If the numbers are
  suggestive but no rule fires, the outcome is **P5** and the suggestion is
  recorded as exploratory, not as a verdict.

## Stop rules

- If arm B cannot be built with work byte-identical to arm A, stop: the
  decomposition depends on it and a padded binary that also changed the work
  would confound the two things it exists to separate.
- If arm C does not reproduce elevation (**P4**), stop and report. Do not
  enlarge the ladder hunting for it.
- On **P4** or **P5**, stop after reporting. Neither licenses a policy change.

## Deliverables

- The arm binaries' sha256s and sizes, recorded before the measurement pass.
- A committed dataset with every raw observation and every `rusage` field.
- A reading that names which rule fired, quoting the arithmetic, and nothing
  beyond it.

## Not yet decided, and deliberately left open for review

- Whether arm B should also be built statically linked, to separate the dynamic
  loader from image size. That would be a fourth arm and a longer round; it is
  proposed and not assumed.
- Whether `process-cold` and `warm` should both be measured, or only
  `process-cold` where every witness lives. Measuring both doubles the round.

These are measurement-design choices and belong to the owner, not to this draft.
