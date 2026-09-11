# Round 7 — what a real invocation does that a synthetic one does not

**STATUS: RATIFIED DESIGN. APPARATUS BUILT. B1–B4 PASSED. OUTCOME CONTRACT
BOUND. PLAN-MODE DRY RUN DONE. NO ROUND 7 MEASUREMENT IS AUTHORISED AND NONE
EXISTS.**

Amended three times. The first review ruled **CHANGES REQUIRED** and decided
four design questions. The second ruled **PASS WITH ONE MECHANICAL CORRECTION**
and ratified a narrower zero rule than the one proposed here. The third reviewed
the implementation, ruled it **PASS**, and then found what the design still did
not say: which bytes get timed, in what order, doing how much work. Those three
gaps are closed below. Timing remains **NO-GO** pending a check of exactly these
bindings.

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

Four further rulings, none of them a question I had asked:

- Arm B's claim was too strong and is weakened, with a structural preflight
  added. See *Arm B claims less than it did*.
- The previous draft's outcome table was not mutually exclusive. See
  *The overlap that made the previous outcome table unreadable*.
- The draft's claim about which witnesses exist was false. See *Correction: the
  witnesses are not all `process-cold`*.
- The degenerate-zero guard proposed here was wrong in both directions: the
  overlap algebra is narrower than claimed, and the guard was wider. The ratified
  rule keys on `A` alone. See *The degenerate-zero guard, as ratified*.

## The apparatus

| file | what it is |
|---|---|
| `scripts/round7/classify.py` | the **one** implementation of P1–P5 and the zero-A guard. Pure: numbers in, an outcome out, no files and no clock. Nothing else in the round may restate the rules — a second copy is a second opinion, and the reading would then be able to choose |
| `scripts/round7/elfread.py` | a minimal ELF64 reader, so the preflight reads program and section headers rather than grepping a tool's prose about them |
| `scripts/round7/pad.c` | arm B's inert image, and only that: no function, no code, never referenced by the work |
| `scripts/round7/preflight.py` | builds the three arms and runs B1–B4. No clock, and none may be added |
| `tests/test_round7_apparatus.py` | five controls, run in CI |

Arm A and arm B are linked from **the same `spin.o`**. Compiling the work twice
and comparing would test the compiler's determinism; linking one object into
both binaries removes the question instead of answering it, and B4 then checks
the only thing left that could differ — what the linker did.

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
| work | fixed arithmetic loop | argv parse, usage refusal on **stdout** |
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

`schedule.process_spawns()` **computes** 2640 from the plan, and a control
compares the two. A number quoted in a document and calculated nowhere is a
number that drifts the first time anything around it changes.

## The execution contract

The design said what to measure and what the numbers would mean. It did not say
which bytes get timed, in what order, or doing how much work — three holes that
no amount of correct classification would have covered.

### Which bytes: one transaction, not two

`scripts/round7/runner.py` does this and nothing else:

    bind work iterations to the Round 6 2 ms rung
            ↓
    build arm A and arm B ONCE
            ↓
    B1–B4 on THOSE EXACT FILES
            ↓
    freeze sha256 and byte length of A, B and C
            ↓
    [plan mode returns here, before any clock]
            ↓
    time THOSE SAME FILES, re-verifying identity before every block
            ↓
    re-verify identity after the last block

The committed preflight proves properties of specific bytes. A runner that
preflighted, discarded its temporary directory, rebuilt and then measured would
prove things about one pair of arms and time a different pair sharing their
names — this project's oldest and most familiar defect, wearing a lab coat.

Identity is re-verified **before every block and after the last**: 41 checks,
all outside the clock, against the alternative of discovering mid-dataset that
something rebuilt an arm underneath the round.

**Plan mode is not a flag that skips the timing loop.** It returns before the
timing function is reachable, and `round7-execution-contract` counts calls to
that function rather than believing this paragraph. Under a mutation that
deletes the early return, the count comes back 240.

### In what order: blocked randomisation, seeded before the data

The previous draft fixed how many sessions and halves and said nothing about
order. Run every A, then every B, then every C, and a machine that drifts over
an hour hands back a beautiful "effect of the real binary" — a result that would
survive every other check in this document.

The ratified schedule:

| | |
|---|---|
| block | `(regime, n, session)` — 2 × 2 × 10 = **40 blocks** |
| within a block | all three arms run, each arm's two halves **adjacent**, arm order deterministically shuffled |
| across blocks | block order deterministically shuffled |
| seed | fixed and committed before any measurement |
| recorded | seed, planned order, **and actual order** |

Blocked rather than a Latin square: drift is spread across arms instead of
aligning with them, and every block contains all three arms, so a within-block
comparison is never a comparison across an hour of machine time.

**The seed is `0xf937b36bd4dac422`** — the first 16 hex digits of the Round 6
helper's sha256, as committed in
`docs/evidence/round6/p022-263a-round6-scales.linux.json` rounds before this one
existed. A literal I invented would be equally deterministic and strictly less
auditable: nothing but my word would stop me re-rolling it until the order
looked tidy. A control checks the constant against that artifact, and catches a
substituted seed.

### Doing how much work: bound to the ladder, not to memory

The draft said "the Round 6 C helper, at its 2 ms rung" and left the number in
prose. It is now read from the artifact that established it:

| | |
|---|---|
| iterations | **460280** |
| source | `docs/evidence/round6/p022-263a-round6-scales.linux.json`, 2 ms rung |
| Round 6 achieved | 2.0128 ms |
| stop condition | arm A's sha256 must equal that file's `helper_sha256` |

Arm A as built **is** the Round 6 helper — `f937b36bd4dac422…`, byte-identical,
so nothing needed recalibrating. If a future build ever differs, the round
**stops**. It does not go looking for a fresh iteration count that lands near
2 ms; that would be calibrating a new knob after authorisation, which is the
move this round exists to forbid.

### And whether the process did the work at all

Calling `Harness._run_once` directly gave this round the instrument's measured
interval and skipped the layer wrapped around it. That layer exists because
twelve cells once timed `command-not-found` accurately and reproducibly, and CI
called it a reproduced calibration.

Nothing in Round 7 checked an exit code. Three arms bound byte-for-byte to the
right binaries could have measured the wrong path with great precision — the
sample clamped perfectly in the vice, and nobody checking whether it was alive.

**Before the clock**, untimed:

| arm | contract |
|---|---|
| **A**, **B** | invoked with 460280 iterations, must exit **0** |
| **C** | the instrument's own `core-usage` rung — `expect_rc` 2 **and** the `usage-help` evidence: stdout names the subcommand, stderr is empty |

Arm C reuses `perf_baseline`'s rung rather than restating it a third time.
Exit 2 is necessary and nowhere near sufficient: a different failure exits 2 as
well, which is exactly what the evidence half is for. A control proves this by
handing the preflight a stand-in that exits 2 and prints nothing; it is refused.

**Every spawn, warmup discards included:**

    A, B → rc must be 0
    C    → rc must be 2

A single stray exit **stops the round and invalidates it**, recording arm,
block, half, whether it was a warmup or a counted sample, its index and the
observed code. Nothing is classified. A discarded iteration that failed has its
numbers thrown away and its evidence kept: it still proves the process is broken.

Only the exit code is read inside the interval. Capturing stdout there would
change what the interval measures, which is precisely why the rich contract runs
once, untimed, and the timed samples check rc alone.

### And a refusal has to leave a black box

Refusing correctly is not the same as recording the refusal. The breach escaped
`run()`, so `main()` never reached its own `--out` write: 239 halves measured, a
stray exit on the 240th, a traceback, and **no file at all**. Nothing to
investigate, nothing to show anyone.

The control was no better. It read `exc.strays` out of the exception object and
called that "recorded" — the in-memory sibling of scoring a mutation by its exit
code, and the same lesson this PR keeps paying for: read the thing, not a proxy
for it.

One boundary handles every `ExecutionContractBreach`, outcome and identity
alike, and writes:

    run_valid: false
    measurements: null
    verdict: INVALID / STOP (<kind>)
    abort:
      kind: outcome-contract | identity-contract
      arm, block, half, spawn_kind, index, observed_rc, expected_rc
      (identity: when, expected_sha256, observed_sha256)

Halves already completed are kept as `partial_measurements`, flagged
`not_evidence: true` with the reason attached. They exist for investigation and
may never be read as data, classified, or compared against anything.

`time_half` now raises on the **first** stray rather than finishing the half.
Once a breach is known, more spawns only produce numbers nobody may use.

`round7-durable-refusal` never looks at an exception. It drives the runner to a
forced stray and to a **real** mid-run identity drift — arm B's bytes genuinely
changed on disk, caught by the real verifier — and then reads the filesystem:
the file exists, the exit code is non-zero, `run_valid` is false, `measurements`
is null, and the abort names the exact spawn or arm. It also checks a healthy
run still calls itself valid, so the control cannot pass by calling everything
invalid.

## The overlap that made the previous outcome table unreadable

The owner found that the previous table's P1 and P4 could both fire on the same
data: `D(A)=1, D(B)=3, D(C)=1.4` satisfies P4 (`D(C) ≤ 1.5·D(A)`) and P1
(`D(B) ≥ 3·D(A)` and `D(C) ≤ 1.5·D(B)`) simultaneously. Ten rounds of insisting
that a check must read the thing, and I preregistered the numbers and forgot to
preregister the logic.

### And then I got the replacement's algebra wrong too

The previous revision of this section claimed that "every overlap between two
rules reduces to `D(A) = 0` or `D(B) = 0`". The owner did the algebra properly
and it does not. The claim "I checked every pair" was again stronger than the
checking behind it.

**Overlap occurs only when `A = 0` AND `B = 0` together.** In particular:

| pair | what the constraints force |
|---|---|
| P4 ∩ P1 | empty for all inputs: P4 needs `C ≤ 1.5A`, P1 needs `C > 1.5A` |
| P1 ∩ P2 | forces `A = 0`, then `B = 0`, then `C = 0`, contradicting P1's `C > 1.5A` — **empty** |
| P1 ∩ P3 | forces `B = 0`, then `A = 0` and `C = 0`, contradicting `C > 1.5A` — **empty** |
| P4 ∩ P2 | `A = B = C = 0` |
| P4 ∩ P3 | `A = B = C = 0` |
| P2 ∩ P3 | `A = B = 0`, with `C` free |

So **P1 is disjoint from every other rule unconditionally**, the zero case
included. The overlaps that remain all need `A` and `B` to be zero together.

This is no longer asserted. `round7-outcome-exclusivity` evaluates the rules
over 50,653 exact rational triples and reports which pairs overlap and where;
the same census is handed the previous draft's P1 and must report it broken,
because a control that has only ever seen correct input is a control nobody has
tested.

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

### The degenerate-zero guard, as ratified

> For each regime: if `D(A) = 0` at **either** repetition count, that regime's
> outcome is **P5**.

`A` only. Not `A` or `B`, which is what the previous revision proposed and the
owner rejected.

**The guard is not what makes the set disjoint.** The algebra above shows the
overlaps need `A = 0` and `B = 0` together, so a rule keyed on `A` alone is
already more conservative than exclusivity requires. The guard exists for a
metrological reason instead: `A` is the **multiplicative reference** for the
whole scheme. `1.5A`, `3A` and `6A` mean something only as multiples of a
baseline that has a size. At `A = 0` any positive `B` or `C` is infinitely
larger than the baseline, and the rules go on classifying — definitely, and
meaninglessly.

**`B = 0` has no such property and is not a refusal.** `A = 1, B = 0, C = 4` is
a clean **P2**: the padded arm shows no excess and the real binary does. That is
one of the cleanest results this round is capable of producing, and the rejected
guard would have deleted it by hand.

**No epsilon.** A tolerance like `A < 0.01 ms` would instantly become a new
absolute threshold with no preregistered basis for its value, which is the exact
move this round forbids. Exact zero is a structural degenerate case, not another
knob. `round7-zero-guard` checks both halves: `A = 0` at either count refuses,
and a tiny but non-zero `A` still classifies.

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
  recorded before the measurement pass. **Done** —
  `docs/evidence/round7/p022-263a-round7-preflight.linux.json`.
- The B1–B4 preflight results, recorded as data, pass or fail. **Done**: all four
  pass. The padding is 1,626,024 bytes in `.rodata`, inside the `PT_LOAD` at
  `0x2000`; arm B maps 1,628,917 bytes against arm C's 1,628,892, a difference of
  **+25 bytes** against a 4,096-byte allowance; and `main` is 107 bytes and
  byte-identical in both arms, so B4 decided on raw bytes and the disassembly
  fallback was not needed.
- A committed dataset with every raw observation and every accounting field, per
  half, per session, per regime, per repetition count.
- A reading that names which rule fired in each regime, quoting the arithmetic,
  and nothing beyond it.

## Authorisation state

**Authorised and done:** all four amendments; the `_run_once` extension; the
apparatus; the B1–B4 structural preflight; the execution contract, schedule and
work binding; the **outcome contract**, timed and untimed; the **plan-mode dry
run**; controls and mutations; CI.

**Not authorised:** the Round 7 calibration pass itself — any timing or resource
measurement; re-recording the sizing pairs; a calibration of record; the D7
freeze; #263-B; merge; Stage 3; Stage 4.

The plan-mode record is committed at
`docs/evidence/round7/p022-263a-round7-plan.linux.json`: arms built, B1–B4
passed on those bytes, identities frozen, the untimed outcome preflight passed
for all three arms (A 0, B 0, C 2 with evidence), 40 blocks and 240 halves
fixed, zero clocks started. The next decision is GO or NO-GO on the measurements, after a
check of these three bindings.
