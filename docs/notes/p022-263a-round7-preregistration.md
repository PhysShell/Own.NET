# Round 7 — what a real invocation does that a synthetic one does not

**STATUS: AMENDED DRAFT. NOT AUTHORISED TO EXECUTE. NOT EXECUTED. No Round 7
measurement exists.**

Amended under the owner's Round 7 review, which ruled **CHANGES REQUIRED** and
decided four design questions the previous draft had left open. What is
authorised right now is this amendment and the instrument change it names —
**not the round**. Execution remains a separate authorisation.

**Tag:** `CALIBRATION_ONLY`. No decisive workload, no threshold, no budget, no
D7 freeze. `0.35` is not consulted anywhere in this round, including in the
reading — that was Round 6's defect and it is not repeated.

## What the owner decided, and where each decision landed

| question | ruling | where it landed |
|---|---|---|
| extend `_run_once` with full POSIX rusage | **YES** | *What must be recorded*, and the instrument change, now made |
| a fourth, statically linked arm | **NO** | removed; the ladder is A/B/C |
| keep arms A/B/C | **YES** | *Design* |
| measure `process-cold` only, or both regimes | **BOTH** | *Regimes*, classified separately |
| run Round 7 now | **NO** | this status block |

Two further rulings, neither of them a question I had asked:

- Arm B's claim was too strong and is weakened, with a structural preflight
  added. See *Arm B claims less than it did*.
- The previous draft's outcome table was not mutually exclusive. See
  *The overlap that made this round unreadable*.

## What Round 6 left

Round 6 was formally **O3, inconclusive**. Descriptively, its ladder was stable
at the durations where real `rust` cells fail: worst absolute drift 0.32 ms
across 27 sessions at 2–10 ms, against 1.23–4.41 ms implied by the historical
failures. Short duration alone does not look sufficient.

The owner's correction to the follow-up: **it is not file I/O.** One of the
witnesses is `core-usage|rust|cal-facts-tiny|process-cold`, and that rung never
opens an OwnIR document — it starts the Rust core, parses argv, and writes a
usage refusal. Input-document I/O is therefore not a necessary condition.

### Correction: the witnesses are not all `process-cold`

The previous draft said the phenomenon lives "only in `process-cold`, where
every witness lives". That is false, and the owner caught it. The five distinct
cells that have fallen outside tolerance at least once are:

| witness | regime |
|---|---|
| `core-full-human\|rust\|cal-facts-small` | `process-cold` |
| `core-usage\|rust\|cal-facts-tiny` | `process-cold` |
| **`core-full-sarif\|rust\|cal-facts-small`** | **`warm`** |
| `core-full-sarif\|rust\|cal-facts-tiny` | `process-cold` |
| `core-full-sarif\|rust\|cal-facts-medium` | `process-cold` |

One of five is `warm`. A round that measured `process-cold` alone would have
been designed around a claim its own evidence contradicts, and would have
reported a `process-cold`-only result as if it covered the phenomenon.

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
| **B** `synth-padded` | the same helper, work byte-identical, padded with an inert mapped array to `core-usage`'s image size | the **padded image footprint and its mapping metadata**, with the work held constant |
| **C** `core-usage` | `own-cli ownir` with no arguments, exit 2 | the real witness, whole |

The decomposition:

- `D(C) − D(A)` — the total excess to be explained
- `D(B) − D(A)` — what a **larger image costs when its extra pages are never
  touched**
- `D(C) − D(B)` — everything else the real binary does: loader symbol
  resolution, runtime startup, argv handling, the refusal write, and any cost of
  its extra pages actually being touched

### The static fourth arm is dropped

The previous draft proposed a statically linked B to separate the dynamic loader
from image size. The owner ruled **NO**. It is not carried forward as a
possibility, a stretch goal, or a footnote; if the loader needs isolating, that
is a later round with its own preregistration.

### A future arm, named so it is not mistaken for this round's

`own-cli --version` would be a **same-binary** arm: identical image, identical
loader, less work. It would separate "the binary is big" from "the binary does
things" without a synthetic stand-in at all. It is **not** part of Round 7 and
is recorded here only so that a later round can find the idea rather than
reinvent it as a mid-round improvisation.

## Arm B claims less than it did

The previous draft said arm B isolates "image size, mapping and **page-fault
cost**". That was wrong and the owner rejected it.

Linux demand-pages an executable image. Padding that is mapped but never read
need not be faulted in at all. Arm B therefore does **not** measure page-fault
cost; it measures what it costs to construct, map and account for a larger
image whose extra pages stay cold.

That makes `D(B) − D(A)` a **lower bound** on any image-related effect, and it
fixes the reading in one specific place:

> If arm B reproduces nothing, the conclusion is **"a padding-only image effect
> is insufficient"**, *not* "image mapping and page faults are excluded".
> A real binary's extra pages are touched; arm B's are not, and the difference
> between those two situations is exactly what arm B cannot see.

### Structural preflight for arm B, run and recorded before any timing

Arm B is worthless if the padding was optimised away, left unmapped, sized
wrongly, or accompanied by a change to the work. Each of those is checked
structurally, on the linked binary, before the measurement pass:

| preflight | what is checked, on the linked ELF |
|---|---|
| **B1 padding survived linking** | the padding symbol is present in the symbol table, and its containing section's size is at least the declared padding size. Declared `const volatile` so neither the compiler nor `--gc-sections` may drop it. |
| **B2 padding is mapped** | the containing section falls entirely inside a `PT_LOAD` program header. Padding present in the file but outside every `PT_LOAD` is not mapped and does not test what B exists to test. |
| **B3 size matches arm C** | the summed `p_memsz` of B's `PT_LOAD` segments matches C's to within one 4 KiB page. The file sizes are recorded alongside, but the mapped size is the one that must match. |
| **B4 the work is identical to arm A** | the work function's bytes are extracted from each binary by symbol offset and size and compared by sha256. Where relocations make raw bytes differ, address-stripped disassembly equality is used instead **and the reading says which test was applied**. |

All four are recorded as data, pass or fail. **B1–B4 are stop conditions:** if
any fails, the round does not proceed to timing. In particular, if B3's mapped
sizes cannot be brought within one page by tuning the padding array, the
achieved delta is recorded and the round **stops for a ruling** rather than
running with a mismatched arm and describing the mismatch afterwards.

## Regimes: both, and what each one actually is

The owner ruled **BOTH**, and corrected what I had assumed the regimes were.
Both are checked against the instrument, not against memory
(`scripts/perf_baseline.py`, `Harness.measure_cell`):

| regime | discarded iterations | process |
|---|---|---|
| `process-cold` | **0** | a fresh process every iteration |
| `warm` | **2** | a fresh process every iteration |

`warm` is **not** an in-process steady state and `process-cold` is **not** a
cold machine. Both spawn a fresh process per iteration. The only difference is
that `warm` throws the first two away, which warms the OS and filesystem caches
rather than any state inside the process. The previous draft's description
contradicted itself on this and is replaced.

Consequences fixed now, before any data:

- Each regime is classified **independently**, producing a pair of outcomes
  `(P_cold, P_warm)`.
- If `P_cold ≠ P_warm`, that is **not** P5. It is a cache- and state-sensitivity
  signal, and it is reported as one, naming both outcomes. A regime split is a
  finding about where the phenomenon lives, and collapsing it into "inconclusive"
  would discard the most informative thing the round can produce.
- The `n=5` / `n=15` agreement requirement below applies **within** a regime.

## What must be recorded, and the instrument change it required

Per run, from the kernel's own per-child accounting:

`elapsed_ns`, `rc`, `peak_rss_bytes`, `cpu_user_ns`, `cpu_system_ns`,
`minor_faults`, `major_faults`, `voluntary_context_switches`,
`involuntary_context_switches`.

`Harness._run_once` previously discarded every rusage field except `ru_maxrss`.
The owner authorised extending it, under four constraints, all of which the
implementation honours:

1. `ru_utime` and `ru_stime` are normalised to **nanoseconds** (rounded, not
   truncated: truncation biases every sample the same direction).
2. The measured interval is **unchanged in meaning** — `t0`, `Popen`, `wait4`,
   `elapsed` — and the rusage is parsed **after** the clock stops. The two
   pre-existing lines between `wait4` and `elapsed` were left where they were:
   moving them would tighten the interval and silently un-compare every future
   number against every recorded one.
3. Nothing is hashed, forked or verified inside the interval. The existing
   `perf-notary-outside` control counts this rather than trusting it.
4. **Off POSIX these six counters are `null` with a stated reason, never zero.**
   There is no Windows equivalent that means the same thing, and a reported `0`
   minor-fault count for a platform that was never asked would be the most
   confident possible lie. `perf-child-accounting` exercises that branch on
   Linux by driving the harness through the non-POSIX path.

This **moves the harness digest** and stales any pair recorded before it. That
was declared in the previous draft as a cost of approval; approval was given and
the change is made. The four committed sizing halves remain stale and are
deliberately not re-recorded.

## Session structure, and a naming collision fixed

The previous draft called the two halves of a measurement session "A" and "B"
while also calling the arms "A", "B" and "C". A reading written in that notation
would have been unreadable at exactly the moment it mattered.

**Arms** are A, B, C. **Session halves** are the *first half* and the *second
half*. A session runs one arm twice, back to back, under one repetition count
and one regime.

Let `D(arm, n, regime)` be the **median across the 10 sessions** of
`|median(second half) − median(first half)|`.

Fixed in advance: `n` in {5, 15}, `warmup` 2 (used only by `warm`), **10
independent sessions per (arm, n, regime)**.

| | count |
|---|---|
| session halves | 3 arms × 2 counts × 2 regimes × 10 sessions × 2 halves = **240** |
| process spawns, `process-cold` | 3 × 10 × 2 × (5 + 15) = 1200 |
| process spawns, `warm` | 3 × 10 × 2 × (7 + 17) = 1440 |
| **total process spawns** | **2640** |

Ten sessions rather than Round 6's five because this round compares arms against
each other, not a single arm against a memory.

## The overlap that made the previous outcome table unreadable

The owner found that the previous table's P1 and P4 could both fire on the same
data: `D(A)=1, D(B)=3, D(C)=1.4` satisfies P4 (`D(C) ≤ 1.5·D(A)`) and P1
(`D(B) ≥ 3·D(A)` and `D(C) ≤ 1.5·D(B)`) simultaneously. Ten rounds of insisting
that a check must read the thing, and I preregistered the numbers and forgot to
preregister the logic.

The ratified replacement below is mutually exclusive. Evaluated pairwise, every
overlap between two rules reduces to `D(A) ≤ 0` or `D(B) ≤ 0`, and `D` is a
median of absolute differences, so the only surviving cases are `D(A) = 0` or
`D(B) = 0` exactly — see the degenerate-zero guard, which is flagged as an
addition and not yet ratified.

## Outcome set, as ratified by the owner

Evaluated per regime, per repetition count. `A`, `B`, `C` abbreviate
`D(A, n, regime)`, `D(B, n, regime)`, `D(C, n, regime)`.

| outcome | rule | what it licenses |
|---|---|---|
| **P4** the witness did not reproduce | `C ≤ 1.5·A` | the round failed to capture the phenomenon in this regime; report and stop |
| **P1** the padded-image effect reproduces the elevation | `C > 1.5·A` **and** `B ≥ 3·A` **and** `(2/3)·B ≤ C ≤ 1.5·B` | a padded image alone lands where the real binary lands; a follow-up may target image construction and mapping |
| **P2** the padding-only effect is insufficient, the real binary is elevated | `B ≤ 1.5·A` **and** `C ≥ 3·A` | the excess is not reproduced by size alone. **This does not exclude image mapping or page faults** — see *Arm B claims less than it did*. |
| **P3** padding contributes but does not explain the whole | `B ≥ 3·A` **and** `C ≥ 2·B` | neither alone explains it |
| **P5** inconclusive | everything else, **or** `n=5` and `n=15` classify differently within this regime | nothing; report and stop |

Note the renames from the previous draft, which the owner required: P1 is no
longer "image mapping dominates" and P2 is no longer "not image mapping". Both
old names asserted more than arm B can see.

**A rule must hold at both `n=5` and `n=15` within a regime to fire.** If the
two counts disagree, that regime's outcome is **P5**. Disagreement *between*
regimes is reported as a cache/state-sensitivity signal, not as P5.

### Proposed addition, NOT YET RATIFIED — the degenerate-zero guard

> If `D(A) = 0` or `D(B) = 0` at either repetition count in a regime, that
> regime's outcome is **P5**.

Reason: at `D(A) = 0` the rules P4 and P2, P1 and P2, and P2 and P3 stop being
disjoint, and at `D(B) = 0` P1 and P3 stop being disjoint. A drift of exactly
zero across ten sessions of nanosecond medians would mean the instrument's
resolution, not the phenomenon. The guard closes the only remaining overlap
without touching any ratified number.

**This is an addition to a ratified outcome set and is marked as one.** It is
put to the owner rather than folded in quietly. The round does not run until it
is ruled on, either way.

### Why ratios and not absolute milliseconds

An absolute boundary would have to come from somewhere. The only available
sources are the failing Owen cells, which are forbidden as input to any rule, or
a number invented to fit, which is worse. A ratio against a baseline arm
measured in the same sessions is self-calibrating and cannot import a threshold
by accident.

### Mechanism attribution, also fixed now

Applied only to whichever arm shows elevation, only after an outcome fires, and
per regime. `Δ` is `second half − first half` within a session; each row is a
median across the ten sessions.

| attribution | rule |
|---|---|
| the work genuinely took longer | median `\|Δ(cpu_user_ns + cpu_system_ns)\|` ≥ `0.5 ×` median `\|Δ elapsed_ns\|` for that arm |
| scheduler | median `\|Δ elapsed_ns\|` ≥ `2 ×` median `\|Δ(cpu_user_ns + cpu_system_ns)\|` **and** median `\|Δ(voluntary + involuntary context switches)\|` ≥ `2 ×` arm A's |
| faults / mapping | median `\|Δ(minor_faults + major_faults)\|` ≥ `2 ×` arm A's |

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
- Adding a fourth arm, static or otherwise, mid-round.
- Reading a P2 as "image mapping and page faults are excluded".
- Any decisive workload, decisive timing, resource exposure of decisive work,
  D7 threshold, C1/C2 freeze, #263-B, Stage 3 or Stage 4.
- Reporting an outcome not produced by the table above. If the numbers are
  suggestive but no rule fires, the outcome is **P5** and the suggestion is
  recorded as exploratory, not as a verdict.

## Stop rules

- Any of preflight **B1–B4** failing: stop before timing. A padded binary whose
  padding was dropped, unmapped, mis-sized or accompanied by a work change
  confounds the two things arm B exists to separate.
- **P4** in both regimes: stop and report. Do not enlarge the ladder hunting for
  the phenomenon.
- **P4** or **P5** in a regime: stop after reporting for that regime. Neither
  licenses a policy change.

## Deliverables

- The three arm binaries' sha256s, file sizes and summed `PT_LOAD` `p_memsz`,
  recorded before the measurement pass.
- The B1–B4 preflight results, recorded as data, pass or fail.
- A committed dataset with every raw observation and every accounting field, per
  half, per session, per regime, per repetition count.
- A reading that names which rule fired in each regime, quoting the arithmetic,
  and nothing beyond it.

## Authorisation state

**Authorised now:** this amendment; the `_run_once` extension; controls and
mutations for the accounting fields; selftests and normal CI.

**Not authorised:** any Round 7 timing or resource measurement; re-recording the
sizing pairs; a calibration of record; the D7 freeze; #263-B; merge; Stage 3;
Stage 4.

The B1–B4 preflight is structural — it reads linked ELFs and runs no clock — but
it is part of the round and is not run ahead of the round's authorisation
either.
