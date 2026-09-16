# P-022 / #263 — T0, the pretraining protocol freeze

```text
Status:
  NOT_FROZEN.
  collection_authorized: false
  CONTENT COMPLETE. HOSTILE FREEZE REVIEW PENDING.
  MANDATORY UNRESOLVED SLOTS: 0 (T0-completion).
  OPEN NORMATIVE CONFLICTS: none. The #262 ratification blocker was withdrawn
    as a misreading — see T0-3.
  NO T0-GOVERNED CLOCK HAS RUN. NO TRAINING OR DECISIVE OBSERVATION EXISTS.
    (Historical calibration and Round-7 observations exist and are untouched
     by this contract; they are not training or decisive evidence.)
```

**What this is.** The contract that fixes *how numbers will be judged*, before any
number exists. It binds the training collection (step 7), the fit (step 8) and
the decisive campaign (#263-B) alike, because a rule chosen after a look at
training data is not a preregistered rule — it is a preference with a timestamp.

**What this is not.** It is not D7. T0 says how a verdict is computed; D7 later
**freezes the rules and the bindings before collection** — the reference, the
harness identity, the workload manifest and a preregistered rule for every cell —
and adds no analytical decision of its own. The measured numbers are not in D7 at
all: they belong to the #263-B evidence produced afterwards. An earlier revision
said D7 "records exact numbers", which described a stronger mechanism than the
one that exists.

**Authority.** T0-0 revoked the automatic authorisation of the first step-7
collection (`docs/notes/p022-263a-step7-environment-capture.md`). Until this
document is frozen, `collection_authorized` is `false` and no training, first or
decisive collection may run, however ready the hosts are.

**The freeze is the authorising act, and it is not sufficient on its own (R15).**
Freezing this contract sets both `status: FROZEN` and
`collection_authorized: true` in the same commit — one owner act, one state — and
the flag is then a *necessary* condition, never a permission slip. Host
qualification, an exact execution binding and a session preflight are still
required, and each can still refuse.

The two fields are read as one state, and three of the four combinations are
refusals:

```text
NOT_FROZEN + false   refuse — the protocol is not fixed
FROZEN     + false   refuse — frozen, but the owner has not authorised collection
NOT_FROZEN + true    refuse — an authorisation without a fixed protocol is a
                              contradiction, and a tool that accepted it would be
                              honouring a flag over the contract
FROZEN     + true    may proceed to the remaining gates, which may still refuse
```

The step-7 tooling enforces this state machine fail-closed; neither the
qualification path nor the binding path may accept `FROZEN + false`.

**Slot discipline.** Every value this document does not already hold appears as a
typed `UNRESOLVED_OWNER_DECISION` slot with its unit and its scope stated. A slot
is filled by an owner ruling recorded here, never by a plausible default and
never by a number suggested by data. A drafter who fills one has replaced the
owner. Equally, a slot is not kept alive because it was once drafted: a
requirement the acceptance contract does not make is removed, not filled with a
zero, an infinity or an "N/A".

---

## T0-1 — Statistic and pairing unit

**RESOLVED.**

The pairing unit is the **cell**, keyed

    (stratum, rung, workload, regime)        stratum ∈ { linux, windows }

Engine is not part of the key: it is the two sides of the pair. This is the
ratified four-part cell identity of §2.1 with `engine` projected out and the
stratum named, so the pair exists exactly where both engines have a timed cell on
**one** platform.

**Pairing never crosses a stratum.** A cell comparison is computed inside one
stratum, and no comparison of any kind is formed over Linux and Windows cells
together. A Linux cell and a Windows cell that agree on rung, workload and regime
are two different cells, because since #355 their memory quantities are not even
the same physical thing:

```text
linux   / launcher-e2e / W / warm   Python vs Rust      one pair
windows / launcher-e2e / W / warm   Python vs Rust      a different pair
across those two                                        no pair, no comparison
```

Every later use of *cell*, *matched pair* and *a class's cell set* inherits this
key. There is no second term for it — a "platform-cell" would
be the same idea with a second name, and two names for one thing is how a
contract starts disagreeing with itself.

**The cell is not the acceptance leaf; a resource inside it is.** A D7 cell
carries two gated resources — elapsed time and the stratum's memory metric — and
each is decided on its own. The leaf is therefore

    (cell, resource)        resource ∈ { elapsed, the stratum's memory metric }

and this document says "resource leaf" wherever the decision is meant, reserving
"cell" for the measurement identity D7 enumerates. An earlier revision called the
cell the leaf, which made two different implementations able to claim they
followed T0.

For each matched pair, per resource:

    P_c = median(Python_c)
    R_c = median(Rust_c)

    relative_regression_c = R_c / P_c - 1
    absolute_regression_c = R_c - P_c

and the rule of T0-5 is applied to **that cell**, on its own, against its
family's budgets. A cell verdict is `PASS`, `FAIL` or `NO_DECISION`; the
roll-ups of T0-3 then combine cell verdicts, never cell numbers.

**Withdrawn: the population-level statistic.** An earlier revision computed
`d_c = log(median(Rust_c)) − log(median(Python_c))`, `D = median_c(d_c)` and
`R = exp(D)` across the whole workload population of a gate, and judged *that*.
It is removed from the decision path for two reasons, both of which the frozen
instrument already rules on:

- a median over workloads **hides a casualty**. One decisive workload degraded
  far past the fail margin disappears behind eleven healthy ones, and the gate
  reports a comfortable ratio for a product that got materially worse on a real
  input;
- it **double-weights an alias**. `large-solution-control` is `alias_of`
  `oss-ShareX.sln` — the same path at the same pin — so a population median over
  manifest entries gives that one solution two votes.

Neither is repaired by choosing a different average. The leaf has to be the cell,
because that is the level at which the accepted D7 gate requires a preregistered
decision, and no aggregate may stand in for it.

**Index pairing is forbidden.** `Rust_i / Python_i` for the i-th iteration is not
a paired observation here and may not be computed, reported or gated on.
`run_calibration` shuffles **cells** under a recorded seed and runs a cell's `N`
iterations back to back, so a Rust iteration and a Python iteration with the same
index are separated by an arbitrary stretch of the session. Pairing them would
assert a temporal correspondence the harness does not produce — the "we matched
the fifth Rust run with the third Python run" defect, in a formula.

**The harness is not to be changed to iteration-level A/B interleaving under T0.**
Doing so edits `scripts/perf_baseline.py`, which is one of the two files in the
harness source set, so it moves the harness identity

    measurement_harness_digest
    104c384d01bf6060bdec1e7c916053ddb04b97fcbd0b39f8a4fc57b8f139672f

to which steps 4, 5 and 6 were **re-bound** after the S8 memory-semantics repair.
Moving it again is a new instrument and a re-evaluation of accepted
instrumentation evidence, not a T0 detail.

**An unpaired cell cannot reach the statistic.** A cell whose invocation did not
do the rung's work is not timed at all and the collection is refused
(instrument §2). Therefore a missing side is an admissibility failure — see
T0-4 — and never a pair dropped quietly from a class's cell set.

**Recorded consequence.** Cell-level pairing cancels *condition* noise (same
stratum, rung, workload, regime, same session, interleaved order). It does not
cancel per-iteration noise, because the data cannot support that claim, and no
stronger noise-cancellation property may be asserted for a cell comparison.

---

## T0-2 — Acceptance margins

**RESOLVED (R5, R6, R7). No open value.**

Two coordinates, never collapsed into a score:

| term | definition |
|---|---|
| `relative_regression_c` | `median(Rust_c) / median(Python_c) - 1`, for one cell |
| `absolute_regression_c` | `median(Rust_c) - median(Python_c)`, for one cell, in its unit |
| unit, time gates | milliseconds — the instrument records `perf_counter_ns`, so the conversion belongs to the reading, never to the evidence |
| unit, memory gates | bytes of the stratum's own `memory_metric`, after the instrument's unit normalisation — resident on `linux`, committed on `windows`, never mixed |

Two margins, because neither alone is meaningful: a relative-only rule fails a
`0.20 ms -> 0.24 ms` change that no user can perceive, and an absolute-only rule
is blind to scale.

Each cell is judged against **two pairs** of budgets — one pair that admits a
pass, one pair that compels a failure — and the decision rule over them is T0-5:

Each budget family below applies to **both regimes** of its resource, on the
stratum named, and to every canonical workload cell inside those classes. The
pass pair and the fail pair belong to the same cell: no regime owns one of them.

```yaml
# R6 — elapsed time. Both strata, both regimes: four of the eight classes, one family.
time:
  M_pass: 0.05             # +5 %
  A_pass: 50               # milliseconds
  M_fail: 0.10             # +10 %
  A_fail: 100              # milliseconds

# R7 — memory. One family per stratum, because the quantities differ.
linux_max_process_peak_resident:     # both regimes
  M_pass: 0.10             # +10 %
  A_pass: 33554432         # bytes, 32 MiB
  M_fail: 0.20             # +20 %
  A_fail: 67108864         # bytes, 64 MiB

windows_max_process_peak_commit:     # both regimes
  M_pass: 0.10             # +10 %
  A_pass: 33554432         # bytes, 32 MiB
  M_fail: 0.20             # +20 %
  A_fail: 67108864         # bytes, 64 MiB
```

**The two memory families carry identical numbers and are not the same budget.**
Resident bytes and committed bytes are different physical quantities; the numbers
agree today because both were chosen from the same product budget before any data
existed, and either may later move without the other. Reading the coincidence as
one cross-platform metric is exactly the error #355 removed from the instrument.

Required of every cell, and true of all three budget families above:

    M_pass < M_fail
    A_pass < A_fail

Both regimes of a resource share that resource's budgets — not because
`process-cold` and `warm` are the same thing, but because the product price of
making a user wait is the same in either. Time and memory do **not** share
budgets: a single absolute value cannot span milliseconds and bytes, and a shared
relative budget would be a tidy symmetry bought with meaning. Nor do the two
strata share a memory budget, for the same reason at one remove: resident and
committed bytes are different quantities that happen to be priced alike. This is
what replaces the old `M`, `A` and `M_A_scope`: three named budget families, with
no scope left ambiguous.

These budgets come from the cutover/product price of latency and memory. They may
not be derived from observed Rust-vs-Python results, calibration variance, or
training output — and none of them was.

---

## T0-3 — Gate population

**RESOLVED (owner rulings R1–R4). The #262 ratification blocker is withdrawn.**

### Why the blocker was withdrawn

An earlier draft of this document carried
`NORMATIVE_RATIFICATION_REQUIRED_AGAINST_262`, on the reading that #262 names
seven phases and demands a gate on each. Reading the issues themselves rather
than a restatement of them dissolves it:

- **#262** says *"Establish and publish **baselines** for"* the seven surfaces,
  delegates their production to #263, and then states the gate separately and
  once: *"Rust must meet an explicit budget and must not materially regress the
  user-visible path."* It also says *"profile before optimizing; JSON and
  rendering may dominate once analysis becomes cheap"* — the per-phase surfaces
  are named there as profiling instruments, not as vetoes.
- **#263**, which produces those baselines, requires measuring separately
  *"where possible"* and *"clearly mark unavailable stages"*.

A phase that cannot be isolated, published as composed and marked unavailable, is
therefore #263's method working as specified, not a contract violation. No
amendment to #262 is required and none is made here.

### Baseline classification, honestly named

Every published stage baseline carries one of exactly four classes, and a derived
number may never be renamed into something stronger than it proves:

| surface | observable | class |
|---|---|---|
| launcher end-to-end run | `launcher-e2e` | `DIRECT` |
| peak memory | `os.wait4` `ru_maxrss` on `linux` (resident) / job object `PeakProcessMemoryUsed` on `windows` (committed), `null` with a reason elsewhere | `DIRECT` where a mechanism exists, and the quantity is named beside the number |
| core startup floor | `core-usage`, composed over `process-startup-core` + `cli-argv-parse` + `cli-usage-refusal` | `DIRECT` as an interval; a **lower bound** on core startup, never relabelled "startup" |
| OwnIR parse | `core-parse-refused - core-usage` | `DERIVED_ASSUMPTION_DEPENDENT` — assumes both invocations pay comparable argv handling and refusal rendering |
| CLI/SARIF rendering | `core-full-sarif - core-full-human` | `DERIVED_EXACT` **for the renderer difference**; imputing "rendering in isolation" from it is not permitted |
| bridge/lowering | member of `core-full-*` | `UNOBSERVABLE_SEPARATELY` |
| analysis | member of `core-full-*` | `UNOBSERVABLE_SEPARATELY` |
| frontend extraction | member of `launcher-e2e` | `UNOBSERVABLE_SEPARATELY` |
| allocations / heap profile | not captured | diagnostic, published where practical (R2) |

`bridge/lowering` and `analysis` share one interval with no boundary between
them. No arithmetic recovers a division the instrument never recorded, and none
is invented here.

### The gates

**R1 — the user-visible path is `launcher-e2e`**, evaluated in two preregistered
regimes, **`process-cold`** and **`warm`**. Both are primary strata of one
user-visible surface and are never collapsed into a single number; #263 requires
cold and warm runs kept distinct. `core-usage` remains a published startup/floor
baseline and profiling evidence, and does not stand in for the cutover gate.

The identifiers are the instrument's own, and this document uses no others:
`process-cold` is a fresh process every iteration with no in-process warmup;
`warm` is still a fresh process, after a stated number of discarded warmup
iterations, with the OS and filesystem caches warm. `machine-cold` is **not
claimed** by the instrument and is therefore not a gate, not a regime and not an
alias for anything here. A bare `cold` is not an identifier in this contract.

**R2 — peak memory** remains a required resource gate wherever the contract
provides a mechanism, and it carries the same regime dimension as time.
`peak_memory_bytes` is captured on every measured cell, and a cell's key includes
its regime, so memory exists separately for `process-cold` and for `warm` rather
than as one number beside the surface. `warm` memory may not hide inside
`process-cold` memory, or the reverse. Allocation and heap profiling is
diagnostic, published for selected workloads where practical; **a missing
allocation profile is neither `INVALID` nor `FAIL`**, and no instrumentation is
added under T0 to obtain one.

**There is no generic "peak RSS" gate in this contract; that name is obsolete.**
The instrument names two different physical quantities and carries the name with
the number, because a witness showed they are not the same thing — a child that
commits 256 MiB and never touches a page is reported in full by the Windows job
object and not at all by `ru_maxrss`:

| stratum | `memory_metric` | what it counts |
|---|---|---|
| `linux` | `max_process_peak_resident` | peak **resident** set over the waited-for descendant chain |
| `windows` | `max_process_peak_commit` | peak **committed** memory of any process in the job |

`resident == commit` is asserted nowhere in this contract, and the two are never
pooled, averaged or compared across platforms. A cell whose `memory_metric` is
not the one its stratum declares does not belong to that gate, and its presence
makes the attempt `INVALID`.

**R4 — Option 2, the current observable surface, with no new diagnostic veto
gates.** Catastrophic per-phase caps were considered and rejected: they are an
acceptance policy #262 does not ask for, and they would turn profiling surfaces
back into hidden vetoes. `K`, `B` and `caps_apply_to` are therefore **removed**
from this contract rather than filled — they are not part of it. Should a real
profile later show the need for such a guardrail, it arrives as its own
owner-ratified amendment, not as a silent passenger inside a preregistration.

### The gate workload population, owned here

The gates are computed over **exactly the decisive workloads of the D7-bound
workload manifest that are applicable to the `launcher-e2e` rung**, and over
nothing else — as **canonical identities**, which is not the same as manifest
entries:

```text
manifest decisive entries at the frozen manifest   13
canonical decisive identities                      12
  large-solution-control is alias_of oss-ShareX.sln
```

**An alias earns no second vote.** `large-solution-control` and
`oss-ShareX.sln` are the same path at the same pin; the manifest declares the
alias precisely so the pair is never counted twice in a denominator. The
instrument resolves an alias to the identity it aliases and refuses a duplicate
canonical identity by name. A population counted in manifest entries would give
that one solution two votes, so the population is counted in canonical
identities and this document says "12 canonical identities at the current
manifest", never "13 voting workloads".

The number is read from the frozen artifacts, not asserted here: it is whatever
the manifest's decisive entries resolve to under the instrument's alias rule, and
it is 12 today.

**Calibration workloads never enter a cutover gate.** They exist to size the
instrument; a gate computed over them would be answering a different question
with the same arithmetic.

The instrument's own applicability rule is an implementation of this sentence,
not the source of it. Population semantics belong to T0: a reader must be able to
say which cells a gate covers without reading a function, and two readers must
not be able to answer differently.

Missing cells are not a smaller denominator. Each of these makes the attempt
`INVALID`, and the semantics match the accepted D7 verifier rather than being
restated loosely here:

```text
a canonical decisive identity absent from the gate set  => INVALID
a cell present for one engine and not the other         => INVALID
an unexpected extra decisive cell                       => INVALID
a duplicate canonical identity (an alias counted twice) => INVALID
a calibration cell inside the gate set                  => INVALID
```

D7 binds the exact workload-manifest digest, and therefore the exact decisive
set: the population cannot be re-read later as "whatever was measured".

### The eight primary gate classes

Since #355 the memory quantity is platform-local, so the identity carries its
stratum. The primary set is exactly **eight gate classes**, four per stratum.

They are **classes, not leaves**: each one covers the canonical decisive
workloads, and the acceptance decision happens per workload cell inside it
(T0-1). Calling them eight gates was the previous revision's error — it implied
one verdict per class computed from an aggregate, which is exactly the masking
this section now forbids.

```text
linux   / launcher-e2e / process-cold / elapsed                     (ms)
linux   / launcher-e2e / warm         / elapsed                     (ms)
linux   / launcher-e2e / process-cold / max_process_peak_resident   (bytes)
linux   / launcher-e2e / warm         / max_process_peak_resident   (bytes)

windows / launcher-e2e / process-cold / elapsed                     (ms)
windows / launcher-e2e / warm         / elapsed                     (ms)
windows / launcher-e2e / process-cold / max_process_peak_commit     (bytes)
windows / launcher-e2e / warm         / max_process_peak_commit     (bytes)
```

**No compensation in any direction**: not workload against workload, not
`process-cold` against `warm`, not time against memory, and not Linux against
Windows. `U_linux` and `U_windows` are never pooled, and no ratio is formed
across them.

### Cells and leaves are not the same count

```text
12 canonical workloads x 2 platforms x 2 regimes   =  48 end-to-end D7 cells
48 cells x 2 gated resources (elapsed, memory)     =  96 acceptance resource leaves
```

The resource axis exists in this contract and **not** in `D7_CELL_DIMENSIONS`;
adding it there would be a schema change, and none is made. The two resource
verdicts of one cell are independent and are combined only by the operator below,
never inside the cell.

### Two roll-ups, one operator

```text
inside a class, over canonical workload cell verdicts:
    any FAIL             => class FAIL
    else any NO_DECISION => class NO_DECISION
    else                 => class PASS

over the eight class verdicts:
    any FAIL             => overall FAIL
    else any NO_DECISION => overall NO_DECISION
    else                 => overall PASS
```

**One failing workload fails its class**, even when every other workload in it
passes. That is the property the withdrawn population median destroyed, and it is
the reason the leaf is the cell.

`INVALID` is **not** a roll-up verdict and never appears at either level: an
admissibility failure invalidates the attempt under T0-4 and T0-6 *before* any
roll-up is computed. A session that reached a roll-up is a session whose evidence
was already complete.

**Memory is gated on `launcher-e2e` only.** The instrument captures
`peak_memory_bytes` on every measured cell and those values are **published as
diagnostic evidence**, but a memory number on a diagnostic rung never gates.
Gating memory on the diagnostic rungs would reintroduce through the resource
metric exactly the per-phase veto R4 removed, which is why the scope is named
here rather than left to a reader.

Every other surface in the table is **published, never gating**. A derived view
may inform a reading and may never serve as a gate.

### How this lands in the accepted D7 payload

The frozen instrument already fixes the shape D7 must fill, and this contract is
written to fit it rather than asking it to move:

```text
D7_CELL_DIMENSIONS = (phase, workload_id, platform, regime)
D7_ROLLUP_LEVELS   = (workload_class, phase, overall_g3)
cell universe      = 8 phases x 12 canonical workloads x 2 platforms x 2 regimes
                   = 384 cells, each needing a rule or an explicit not_applicable
```

**What the accepted verifier proves, and what it leaves open.**
`_d7_protocol_problems()` requires `rollups` to be an object carrying
`workload_class`, `phase` and `overall_g3`, each `_present`, and `_present`
inspects presence and container shape only — "nothing compares, orders, or
records a value, so no threshold can leak through the verifier". That is right
for a gate forbidden to read a threshold, and it has a consequence this contract
must absorb: **the verifier would accept several different reductions**, and no
accepted artifact says what the three levels mean. So T0 says it. A freeze whose
serialization is settled afterwards by "it was obvious what we meant" is not a
freeze.

The mapping, stated so nobody has to infer it:

- the **time** classes are the `end-to-end-csharp` phase, per platform and
  regime — the user-visible path, and the only phase this contract gates;
- the **memory** classes are not a phase. Memory is decided on the same cells
  through the cell's `rss_policy` key, which is why this document never asks D7
  for a memory phase it does not have;
- the other seven phases carry an explicit `not_applicable` with the reason
  "published as diagnostic evidence; not a cutover gate under T0-3" — under R4 a
  diagnostic surface never becomes a veto, and D7 completeness is satisfied by a
  recorded decision rather than by silence. A `not_applicable` cell contributes
  **no verdict at any level**, so no diagnostic phase can move the acceptance
  outcome in either direction;
- the per-cell rule keys are filled by this contract: `pass_fail_rule` and
  `inconclusive_band` by T0-5, `bound` by the T0-2 families, `comparison_statistic`
  by T0-1's per-cell ratio and difference, `repetition_ladder` by R14,
  `rss_policy` by the stratum's memory metric, `allocation_policy` by R2's
  diagnostic-only ruling.

### Two resources inside one D7 cell

A D7 cell identity has no resource axis: `(end-to-end-csharp, workload_id,
platform, regime)` is one cell, and this contract produces **two** independent
verdicts on it — elapsed time and memory. Where each rule lives is fixed here, so
a payload author cannot choose an interpretation afterwards:

```text
bound                 { "elapsed": <the T0-2 time family>,
                        "memory":  <the T0-2 family of this cell's platform> }
pass_fail_rule        { "elapsed": <T0-5 rule>,      "memory": <T0-5 rule> }
inconclusive_band     { "elapsed": <T0-5 gray zone>, "memory": <T0-5 gray zone> }
comparison_statistic  { "elapsed": <T0-1 per-cell ratio and difference>,
                        "memory":  <the same, on this cell's memory metric> }
rss_policy            names this cell's platform-local metric:
                      max_process_peak_resident on linux,
                      max_process_peak_commit on windows
allocation_policy     diagnostic only, never gating (R2)
repetition_ladder     single-stage, by R14: initial_n = max_n = N, both
                      mechanisms recorded as {kind: none}, terminal outcome is
                      the cell verdict. Identical for both resources
```

`_present` accepts a non-empty object, so these nested rules are structurally
valid under the accepted verifier: **no schema change, no instrument change, and
the harness digest does not move.**

Both resources yield **independent leaf verdicts** that enter the reduction side
by side. A `FAIL` on either is never compensated by a `PASS` on the other, and a
`NO_DECISION` on either propagates unless the other is `FAIL` — not as a special
case, but as the ordinary behaviour of the operator below.

### Why the serialized reduction returns the same verdict

T0 reduces cell verdicts to eight class verdicts to one overall verdict; the D7
payload reduces at `workload_class`, then `phase`, then `overall_g3`. These must
not be two different answers wearing one name, so the equality is proved rather
than asserted.

The roll-up operator is **maximum under the total order**

```text
PASS  <  NO_DECISION  <  FAIL
```

"any FAIL ⇒ FAIL; else any NO_DECISION ⇒ NO_DECISION; else PASS" is exactly `max`
over that order. Maximum over a total order is **associative, commutative and
idempotent**, so the result depends only on the *set* of leaf verdicts and never
on how they are grouped, ordered or nested. Therefore:

```text
workload_class :  max over the canonical workload leaf verdicts of one
                  (platform, regime, resource)            -> a class verdict
phase          :  max over the class verdicts of end-to-end-csharp;
                  not_applicable cells contribute nothing
overall_g3     :  max over the phase level — which by associativity equals
                  max over all eight class verdicts, which is T0's own roll-up
```

The two reductions are the same function of the same multiset, so they cannot
disagree.

Regrouping is safe **only for discrete verdicts**. No elapsed or memory *number*
is ever pooled, averaged or otherwise combined across workloads, regimes,
platforms or resources: the algebra above applies to the three words `PASS`,
`NO_DECISION` and `FAIL`, and to nothing else.

### The campaign join, and what it is not

The accepted D7 payload binds `python_reference_commit`,
`python_reference_tree`, `harness_digest`, `harness_version` and
`workload_manifest_sha256`. It does **not** bind the execution binding:
`execution_binding_sha256` appears nowhere in `D7_PAYLOAD_BINDING_KEYS`, and the
string `execution_binding` does not appear in the instrument at all. The gate
checks that the listed keys are *present* and matching; an extra key in the
payload is tolerated and never verified. So a payload could name a campaign and
the gate would not notice if it named the wrong one.

That gap is closed by a **campaign link**, an artifact of the step-7 layer that
ties the three identities together and is verified fail-closed before the clock
and again after it:

```text
campaign link binds, by exact bytes:
    execution_binding_sha256
    the D7 payload's sha256, its blob id and the commit that carries it
    the D7 attestation's exact identity
```

**A decisive session is admissible only with it.** The session preflight refuses
to start when the link is absent, when it does not name this execution binding,
or when the D7 payload and attestation now on disk do not hash to what the link
names; the postflight refuses to issue an admissibility record on the same
grounds. Admissibility under this contract *is* the existence of that postflight
record, so evidence produced without the link is not inadmissible by opinion —
there is no artifact that can say it is admissible.

**What the link does not do, stated plainly.** It does not make the instrument's
firewall aware of the campaign. The `IdentityGate` arms from the D7 payload and
attestation alone, so a decisive clock can physically run with no execution
binding in existence; what cannot happen is that such a run becomes admissible
evidence. Making the firewall itself refuse would require editing
`scripts/perf_baseline.py`, which moves `measurement_harness_digest` and re-opens
steps 4, 5 and 6 — a price this contract does not pay for a property it can
obtain by making admissibility, rather than execution, the thing that is gated.

Nothing here requires a change to `scripts/perf_baseline.py`, and therefore
nothing here moves the harness digest.

---

## T0-4 — Decision automaton

**RESOLVED.**

Terminal states are exactly four, and the reading is a function of evidence, not
prose:

```text
eligibility (T0-7: host qualified, every required primary metric has a
             working mechanism on it)
   │
   ├─ not eligible ────────────────────────► collection does not start
   │                                          (no attempt, no evidence, no verdict)
   └─ eligible
        │
        admissibility (T0-6 invalidation predicates, incl. a required primary
                       metric that returned null or went missing mid-attempt)
        │
        ├─ violated ───────────────────────► INVALID attempt ─► retry (T0-6)
        │                                     └─ budget exhausted ─► NO_DECISION
        └─ clean
             │
             every canonical workload cell, by the two-dimensional rule of
             T0-5 over its family's T0-2 budgets, then rolled up inside its
             class and over the eight classes (T0-3)
             │
             ├─ any class FAIL ────────────► FAIL          ─► NO_GO
             ├─ any class NO_DECISION ─────► NO_DECISION
             └─ all eight classes PASS ────► PASS          ─► GO
```

The three null-metric situations are **different states**, and collapsing them
into one switch was the defect this section used to carry:

| situation | outcome |
|---|---|
| **A.** Before collection: a required primary metric has no mechanism on this host or session | the host/session is **not eligible**; collection does not start |
| **B.** Collection was eligible, but a required primary metric returned `null` or went missing during the attempt | the attempt is **`INVALID`** — evidence that should exist is damaged |
| **C.** Retry budget exhausted after `INVALID` attempts | **`NO_DECISION`** |

`null primary metric => PASS` is structurally unreachable, in every one of the
three.

`INVALID` and `NO_DECISION` both surface as `NO_DECISION` at the cutover level,
and are kept apart because they mean different things: `INVALID` says the
measurement did not happen properly, `NO_DECISION` says it happened and did not
resolve.

### The numeric domain, before any rule is applied

Every quantity a primary gate consumes must be **defined, real and finite**
before T0-5 is reached. Per cell:

```text
median elapsed > 0
median memory  > 0        (the stratum's own metric)
```

and for each cell's derived quantities `relative_regression_c` and
`absolute_regression_c`, any of

```text
None · NaN · +inf · -inf · undefined arithmetic
```

makes the **whole attempt `INVALID`**. A negative finite regression is not in
that list: it is an improvement, and it passes.

This is checked **before** the two-dimensional rule, not inside it, because the
rule's `OR` would otherwise let an undefined coordinate through on the strength
of the other one:

```text
relative = NaN,  absolute = 10 ms   =>  INVALID, never PASS
relative = 0.01, absolute = NaN     =>  INVALID, never PASS
```

A comparison against an undefined number is not a comparison that failed, and it
is certainly not one that succeeded.

### Sample completeness

A primary cell is admissible only when it holds **exactly the preregistered `N`**
samples. For elapsed time:

```text
observed elapsed samples == N
every sample finite and > 0
```

and for memory:

```text
observed memory samples == N
every sample present, finite and > 0
every sample carries the memory_metric its stratum declares
```

**One `null`, one missing sample or one unexpected metric kind makes the session
`INVALID`.** A median over the surviving subset is forbidden: the instrument's
summariser drops absent memory samples on the way past, so without this rule a
cell that lost half its measurements reports a confident median of the half that
survived. That is the defect this clause exists to close, and it is closed here
rather than in a reading nobody re-reads.

---

## T0-5 — Uncertainty rule

**RESOLVED (R5): a deterministic gray zone in two dimensions.**

The gray zone is defined on the same two coordinates the margins are, and no
synthetic scalar score is constructed from them. This is the **per-resource-leaf
decision function**, applied to one resource of one cell against the budget
family that resource belongs to:

```text
PASS          iff  relative_regression_c <= M_pass
               OR  absolute_regression_c <= A_pass

FAIL          iff  relative_regression_c >= M_fail
              AND  absolute_regression_c >= A_fail

otherwise     NO_DECISION
```

**An earlier draft was underdetermined and this replaces it.** T0-2 gives two
coordinates; that draft's `value <= PASS_LIMIT` named a scalar nothing produced,
and left "which number is `value`" — relative, absolute, some normalisation, the
larger of the two — unanswered. The answer was not a limit to be chosen later; it
was a missing dimension. `PASS_LIMIT`, `FAIL_LIMIT` and `gray_zone_margin_binding`
are therefore removed as symptoms of the wrong model rather than filled in.

The two-dimensional form keeps what the dual-margin rule was for in the first
place: a small absolute difference does not become a problem merely because the
baseline is microscopic, and a small relative difference does not become a problem
merely because the workload is enormous. Between "cheap on either coordinate" and
"expensive on both" there is now a real gray zone, and it is named.

**The two conditions cannot both hold.** `PASS` via the relative coordinate
requires `relative_regression_c <= M_pass < M_fail`, which contradicts `FAIL`'s
`relative_regression_c >= M_fail`; `PASS` via the absolute coordinate contradicts
`FAIL`'s absolute condition the same way, because `A_pass < A_fail`. The ordering
requirement in T0-2 is what makes the per-gate function total and single-valued —
one of `PASS`, `FAIL`, `NO_DECISION`, never two.

**Why not a bootstrap over cells.** The cells are a fixed, preregistered set of
acceptance strata — an engineering choice of workloads, rungs and regimes — not
an IID sample drawn from a natural population. Resampling them produces an
interval that looks like statistical inference while describing the drafter's
workload list, and it would lend that list an authority it has not earned. The
gray zone is cruder and honest: it says where the contract refuses to call a
winner, and it says so in the same units as the margins.

It also removes a post-hoc surface a bootstrap would have kept open — the
confidence level, the resampling unit, the resample count and the seed would each
have had to be frozen, and each would have been a place to negotiate with the
data afterwards.

The zone's boundaries are the budget families of T0-2 and nothing else: there is no
separate limit to set here, which is the point of removing the scalar pair. They
may not be derived from training results, calibration variance or any observed
comparison.

---

## T0-6 — Invalidation and retry

**RESOLVED (R8, R9).**

The unit of invalidation is the **session** — the whole predefined measurement
unit, as the instrument already treats it. A phase, a cell or a workload is never
invalidated, rerun or replaced on its own.

Invalidation fires only on machine-detectable predicates frozen in advance:

- opening or closing noise probe relative IQR above `NOISE_PROBE_MAX_RELATIVE_IQR`
  (0.35);
- drift between opening and closing probes above `NOISE_PROBE_MAX_DRIFT` (0.35);
- a cell that did not do its rung's work, proved by its post-condition;
- a required primary metric that returned `null` or went missing mid-attempt
  (T0-4 case B);
- a primary cell holding other than exactly `N` samples, or a sample that is
  absent, non-finite or not greater than zero (T0-4, sample completeness);
- a sample carrying a `memory_metric` other than the one its stratum declares;
- a gate quantity that is undefined, non-real or non-finite (T0-4, numeric
  domain);
- a gate cell set that is not exactly the decisive population of T0-3 — a missing
  decisive workload, a missing engine side, an unexpected extra cell, or a
  calibration cell that found its way in;
- identity-field drift in the step-7 environment manifest, fields compared whole,
  on the post-session recheck (R9);
- candidate byte drift within a stratum after collection started.

**A performance result is never an invalidation condition.** Not a slow cell, not
a gray-zone outcome, not a disappointing cell comparison — and, since this
revision, not a failure to reproduce a median either.

**Statistical non-reproduction is not `INVALID` and buys no retry.** An earlier
revision listed a reproducibility median change above
`REPRODUCIBILITY_MAX_MEDIAN_CHANGE` among the invalidation predicates, which
turned an observed number into a ticket for another throw of the coin — the
outcome-selective surface this contract exists to close. The accepted instrument
keeps the two questions apart on purpose: `timings_reproduced` and
`environment_valid` are separate verdicts, and a timing disagreement does not
establish whether contention, a variable workload or the uncertainty of a median
caused it. `INVALID` remains for integrity and environment failures that are
knowable without looking at the comparison: noise and drift probes, missing or
corrupt evidence, the wrong population, identity or candidate drift, a missing
required metric, a broken numeric domain. Reproducibility keeps the meaning the
accepted calibration policy gives it, and T0 does not reclassify it. Every predicate above is
machine-detected, so no operator chooses to invalidate a session.

One retry attempt is one full re-collection of the invalidated session on the
same qualified host. Every attempt, including invalidated ones, is retained as
evidence and none is deleted.

```yaml
retry_budget: 1        # R8
```

**Scope: the decisive campaign only.** `retry_budget` governs #263-B and nothing
else. Step-7 training keeps the rule its own frozen preregistration already
carries — `exactly_one_collection`, `abort_semantics.no_automatic_retry`, and an
`INVALID` training collection yields no admissible Step-8 input. No training
attempt is created by R8, and this document does not amend Step 6 by implication:
a fixed thirty-run collection does not remain the same object after a second
attempt, whatever a later reader would prefer.

Read literally, for the decisive campaign:

    1 initial attempt
    + at most 1 full-session retry after INVALID
    = at most 2 attempts per stratum

After a second `INVALID`, the outcome is `NO_DECISION`. There is no third throw
of the coin. One retry survives a genuine one-off environmental failure; a larger
budget would turn the campaign into a machine that runs until the infrastructure
eventually cooperates.

### R14 — decisive repetition is single-stage

Training selects one global `N` under T0-9. That `N` is both the initial **and**
the maximum sample count of the decisive campaign. **There is no decisive
escalation after a result has been seen.**

```text
initial_n = N
max_n     = N

collect exactly N samples for the cell
apply the T0-4 admissibility rules
apply the T0-5 decision

PASS         => terminal
FAIL         => terminal
NO_DECISION  => terminal
```

`NO_DECISION` is never a transition predicate and never licenses a larger `N`.
`INVALID` does not belong to the repetition ladder at all: it is handled by the
retry mechanism above, and only `INVALID` with retry budget remaining permits a
full repeat session — **at the same `N`**, which makes it a retry and not an
escalation stage.

The reason is recorded rather than left to be reconstructed:

- T0-9 lets training derive `N` and nothing else, so an escalation ladder has no
  owner who is allowed to choose it;
- sample completeness (T0-4) already requires *exactly* `N` samples in a primary
  cell, and a cell that grew to `N + k` would fail its own admissibility rule;
- T0-5 deliberately makes the gray zone a terminal `NO_DECISION`;
- an adaptive `N -> larger N` after seeing a decisive result would create a new
  post-observation degree of freedom — the campaign asking for more data
  precisely because the data it has did not answer conveniently. A
  preregistration turns into a menu at exactly the moment a menu is least
  affordable.

**The exact D7 representation**, fixed here so the word "none" cannot become a
freedom later. The accepted verifier's `_present()` treats an empty list or
object as absent, so the two absent mechanisms are written as non-empty objects
rather than as `[]`:

```yaml
repetition_ladder:
  initial_n: N                 # the single global N selected by T0-9 training
  escalation_stages:
    kind: none
  transition_predicates:
    kind: none
  max_n: N
  terminal_outcome:
    kind: cell_verdict
    values:
      - PASS
      - FAIL
      - NO_DECISION
```

`N` is substituted with the selected value when the D7 payload is built; nothing
else in this block is a choice. Should a JSON serialization need different
syntax, it must preserve **this** semantic structure: a non-empty object
`{"kind": "none"}` for each absent mechanism, never an empty container and never
free prose.

**Manifest refresh is per session (R9).** A fresh environment manifest is
captured before every measurement session, and the identity-bearing fields are
rechecked after it; drift between the two is `INVALID`. A campaign-level manifest
is too weak: between an update, a reboot, a governor change and the other ways a
computer gets improved, it can become a historical document before the second
session starts.

---

## T0-7 — Host eligibility predicate

**RESOLVED (R10–R13).**

Already normative, from the existing contract:

- `NOISE_PROBE_MAX_RELATIVE_IQR` 0.35, `NOISE_PROBE_MAX_DRIFT` 0.35,
  `REPRODUCIBILITY_MAX_MEDIAN_CHANGE` 0.35, all chosen before the runs they judge
  and not to be re-chosen to make a host pass;
- a GitHub-hosted runner is not measurement-grade — established on one commit,
  where two Windows runs minutes apart disagreed about their own validity;
- the decisive Windows measurement needs a single-tenant machine, and D7 may not
  preregister a Windows protocol that assumes a hosted runner;
- both strata are required: `U_linux` and `U_windows`, never pooled;
- a step-7 environment identity manifest per host, identity fields compared whole;
- `host_fingerprint` inside a container is the container's identity, so a
  container is not a host;
- per-stratum untimed builds, with `candidate_sha256` and `candidate_bytes`
  identical across every run of that stratum;
- **every required primary metric must have a working mechanism on the host**
  before the session is eligible (T0-4 case A). On a host where the stratum's
  memory metric has no
  mechanism, the session does not start; it does not start and then fail.

### R10 — single tenancy, in two classes of evidence

A guest OS cannot look at the hypervisor and establish that no neighbour has
appeared on the same iron. Pretending otherwise would be security theatre in a lab
coat, so the predicate separates what is declared from what is checked, and never
calls the declaration a proof.

```yaml
single_tenant_predicate:
  provisioning:                 # declared, recorded as evidence, shape-checked
    dedicated_to_p022: true
    no_concurrent_user_workload: true
    hosted_ci_runner: false
    if_vm:
      fixed_vcpu: true
      fixed_ram: true
      live_migration_disabled: true
      dynamic_memory_disabled: true
  runtime:                      # machine-verified each session
    host_fingerprint_stable: true
    logical_cpu_count_stable: true
    memory_bytes_stable: true
    candidate_identity_stable: true
    ci_environment_absent: true    # the manifest's own `ci` provenance field
```

The checker asserts the presence and shape of the provisioning declaration and
verifies every runtime invariant. It does not claim the first class is machine
proof.

### R11 — power policy

```yaml
power_policy_requirement:
  linux:
    governor: performance            # on all applicable CPUs
    turbo_boost_state: recorded and unchanged through the session
  windows:
    power_plan: High Performance OR Ultimate Performance
    processor_minimum_state: 100
    processor_maximum_state: 100
    active_plan_identity: unchanged through the session
```

Turbo is **not** forcibly disabled. The subject is a production-like code path,
not SPEC CPU in a monastery, and instability is what the noise and drift probes
exist to catch.

### R12 — permitted background

Baseline OS services are permitted; this is not a debloat ritual. Prohibited for
the duration of a session:

```yaml
permitted_background:
  prohibited_during_session:
    - OS or package updates
    - scheduled antivirus or full scans
    - backup jobs
    - indexing rebuilds
    - build or test workloads unrelated to the campaign
    - interactive user workloads
```

Windows Defender realtime protection is not itself prohibited. If it makes the
environment unstable, the noise and drift predicates catch it — that is a
measurement question, not a reason to switch off a security stack by ritual.

### R13 — quiesce procedure

```yaml
quiesce_procedure:
  before_session:
    no_campaign_workload_for: 120 s
    during_final: 60 s
    mean_host_cpu_utilisation_below: 0.05
    no_5_second_sample_above: 0.20
    no_prohibited_background_job_active: true
  then: opening noise probe
  after_session:
    - closing noise probe
    - environment identity recheck
```

**A quiesce failure is `not eligible to start`, never `INVALID`** — no clock has
run, so there is no evidence to damage and nothing to retry. It therefore consumes
no retry budget, and it cannot be outcome-selective: a session that never started
produced no number to prefer.

The existing 0.35 noise, drift and reproducibility limits apply unchanged after
this point.

Reconnaissance already performed on a shared developer workstation remains
**exploratory only**: it informed the shape of this predicate and contributes no
measurement, no manifest and no qualified host.

### What the tooling owes this section

The qualification layer implements these rules; it does not own them, and its
schemas are not restated here. T0 fixes the rule, the tooling fixes the
representation:

```text
a qualification names the exact FROZEN T0 it was earned against
an execution binding names both strata, both candidates and the instrument
every session record names the execution binding it belongs to
a fresh environment manifest per session, identity compared as a whole
preflight before the clock, postflight after it
```

A qualification earned against a different T0 is not evidence under this one, and
a session that cannot name its binding does not belong to this campaign.

---

## T0-8 — Selection and replacement

**RESOLVED.**

1. Qualification runs no Rust-vs-Python benchmark. A host is qualified against the
   predicate and the noise floor, never against how the comparison came out.
2. The first host that passes the predicate, in a predeclared order, becomes the
   host of its stratum.
3. After any outcome-bearing data exists, a host may be replaced only for one of
   the six conditions below. **A performance outcome is never a replacement
   reason.**
4. Replacement begins with full requalification.
5. Every replacement records: reason, the rule invoked, old identity, new
   identity, time and order. Evidence from the replaced host is retained.

### The replacement conditions, exhaustively

```text
1. the host is permanently unavailable
2. hardware failure
3. OS or environment identity drift that cannot be restored
4. the required power-policy qualification cannot be restored
5. a required measurement mechanism is permanently unavailable
6. the provisioning guarantee is withdrawn
```

The wording of a condition may be sharpened; the class may not be widened. There
is deliberately no sixth-and-a-half "other environmental reason": a list with an
escape hatch is a list of one entry, and that entry is "whatever we felt".

### Retry continuity — the budget belongs to the stratum

```text
retry_budget is a property of the STRATUM, not of the host
host replacement does NOT reset it
```

If one `INVALID` has already spent the budget, a replacement host does not buy
another attempt. Otherwise a campaign could walk from machine to machine
collecting attempts until one of them came out well, which is the same failure
mode as an unbounded retry with extra paperwork.

**A valid outcome-bearing session is retained as evidence forever**, and its
existence is what closes the stratum: once a valid `PASS`, `FAIL` or
`NO_DECISION` exists for a stratum, host replacement cannot create another
attempt. Re-measurement is permitted only when

```text
the previous attempt was INVALID   AND   retry budget remains
```

A new binding identity does not erase the history of the old campaign attempt: it
starts a new campaign beside it, and both remain in the record.

Every replacement additionally records the **old and new execution-binding
identities** and the **retry budget remaining** after it, so a reader can see
what a replacement did and did not buy.

Workloads and inputs are already frozen — 13 decisive entries, pinned. Drift on a
pinned target is a **failed target**, never a newer measurement and never a
substitution.

---

## T0-9 — Training degrees of freedom

**RESOLVED.**

Training may derive **`N` and nothing else**, by the already-ratified rule: the
ladder `[5, 15, 45]`, `G = [1, 10]`, per-stratum admissible sets
`Q_p = { N : W_p(N) <= (1+G) * min_N W_p(N) }`, selection = the smallest rung in
`Q_linux ∩ Q_windows`, and `NO_COMMON_N` is a stop with no fallback rung.

Training may not change, and seeing training output grants no licence to revisit:
the statistic, the pairing unit, any budget of any family, the gate
population, the two-dimensional decision rule, the decision automaton, retry
semantics and budget, manifest refresh, host eligibility semantics, or workload
selection and replacement rules.

---

## T0-completion

**No `UNRESOLVED_OWNER_DECISION` slot remains.** Every value this contract needs
is now in it:

| what | where | ruling |
|---|---|---|
| three budget families, time and one per stratum's memory metric | T0-2 | R6, R7 |
| the two-dimensional decision rule | T0-5 | R5 |
| `retry_budget: 1` | T0-6 | R8 |
| single-stage decisive repetition, and its exact ladder serialization | T0-6 | R14 |
| `manifest_refresh_rule: per session` | T0-6 | R9 |
| single-tenancy, in two evidence classes | T0-7 | R10 |
| power policy, per platform | T0-7 | R11 |
| permitted background | T0-7 | R12 |
| quiesce procedure | T0-7 | R13 |
| the decisive gate population | T0-3 | S1 |
| the numeric domain and sample completeness | T0-4 | S2, S3 |
| eight platform-qualified gate **classes** | T0-3 | S8 |
| the leaf decision: one verdict per (cell, resource) leaf | T0-1, T0-5 | P3.5, F2 |
| the authority state machine, freeze as the authorising act | preamble | R15 |
| the campaign link joining execution binding, D7 payload and attestation | T0-3 | F1 |
| the within-class roll-up over canonical workload verdicts | T0-3 | P3.5 |
| the overall roll-up over the eight class verdicts | T0-3 | P3.5 |
| the D7 serialization and its equivalence proof | T0-3 | P3.5 |
| the exhaustive replacement list and retry continuity | T0-8 | S7 |

Removed rather than filled, because the acceptance contract does not make the
requirement: `K`, `B`, `caps_apply_to` (R4); `null_primary_metric_outcome`
(replaced by the three distinct states of T0-4); and `PASS_LIMIT`, `FAIL_LIMIT`,
`gray_zone_margin_binding` (R5 — symptoms of a scalar model that did not match the
two coordinates the margins are defined on). Superseded: `M`, `A` and `M_A_scope`,
by the three typed budget families of T0-2. Closed as a misreading: ratification of
the gate population against #262 (R3).

**`status: NOT_FROZEN` stands until a hostile freeze review is completed.**
Content completeness is not the freeze; it is what makes the freeze reviewable.
`collection_authorized: false`.

---

## Hostile review after the rulings

| question | answer |
|---|---|
| see training data, then change the statistic? | **no** — T0-1 resolved, T0-9 forbids revisiting |
| change the pairing definition? | **no** — index pairing named and forbidden |
| change the primary gate population? | **no** — T0-3 resolved under R1/R4; a new gate is an amendment, not an adjustment |
| reintroduce per-phase vetoes quietly? | **no** — the caps were removed from the contract, and a derived view may never gate |
| pick the uncertainty model after the data? | **no** — deterministic gray zone chosen, with its rationale recorded in T0-5 |
| change a budget after seeing a number? | **no** — all eight are set, and T0-9 forbids revisiting |
| construct a scalar score and argue about which number it is? | **no** — the rule is two-dimensional and no scalar exists to construct |
| raise the retry budget after a failure? | **no** — `retry_budget: 1`, and a second `INVALID` is `NO_DECISION` |
| invalidate a session deliberately to buy a retry? | **no** — every invalidation predicate is machine-detected, and a performance result is never one |
| re-run quiesce until the machine looks good? | **permitted, and harmless** — a failed quiesce starts no clock and produces no number, so it cannot be outcome-selective; it consumes no retry budget |
| replace a host because the result is unpleasant? | **no** — T0-8 rules 3 and 5 |
| can a missing or null primary metric yield PASS? | **no** — structurally, in all three T0-4 states |
| can a host with no mechanism for a required metric start a session? | **no** — T0-7 eligibility, T0-4 case A |
| can a stale manifest carry a campaign? | **no** — fresh per session, rechecked after, drift is `INVALID` |
| can anyone start collecting because hosts and binding are ready? | **no** — T0-0 revoked that; `collection_authorized: false` |
| can one evidence set yield both PASS and FAIL under two admissible readings? | **no** — per cell the two conditions are mutually exclusive by `M_pass < M_fail` and `A_pass < A_fail`, and both roll-ups are total functions of the verdicts beneath them |
| does the declaration of single tenancy masquerade as proof? | **no** — provisioning evidence and runtime invariants are separated, and only the latter is called machine-verified |
| can a calibration workload enter a cutover gate? | **no** — T0-3 owns the population: decisive workloads applicable to `launcher-e2e`, and a calibration cell in the set is `INVALID` |
| can a missing decisive workload quietly shrink the denominator? | **no** — a missing workload, a missing engine side or an unexpected extra cell each make the attempt `INVALID` |
| can a cell with fewer than `N` samples still produce a median? | **no** — a primary cell holds exactly `N`, every sample finite and positive; one `null` invalidates the session rather than yielding a median of the survivors |
| can an undefined quantity reach a verdict through the rule's `OR`? | **no** — the numeric domain is checked before T0-5; `NaN` on either coordinate is `INVALID`, never `PASS` |
| can Linux resident bytes be compared with Windows committed bytes? | **no** — the metric is part of the gate identity, the strata are never pooled, and `resident == commit` is asserted nowhere |
| can a replacement host buy another attempt? | **no** — the retry budget belongs to the stratum, replacement does not reset it, and a valid outcome closes the stratum |
| can one degraded workload hide behind the others? | **no** — the leaf is the cell; one `FAIL` fails its class however many workloads pass, and the population median that allowed it is withdrawn by name |
| can an alias vote twice? | **no** — the population is counted in canonical identities, an alias resolves to what it aliases, and a duplicate canonical identity is `INVALID` |
| can a workload be dropped to improve a class? | **no** — a missing canonical identity is `INVALID`, not a smaller denominator |
| does reordering the workloads change a verdict? | **no** — the roll-up operator is order-independent by construction, and it is checked that way |
| does T0 ask D7 for a payload it cannot express? | **no** — time maps to the `end-to-end-csharp` phase, memory to each cell's `rss_policy`, and the seven non-gating phases carry an explicit `not_applicable` with a reason |
| can a valid result be re-measured on a new host? | **no** — re-measurement needs a previous `INVALID` **and** remaining budget; a new binding starts a campaign beside the old one and erases nothing |

No "yes" answer remains that a decision could close. The one permitted item — a
repeated quiesce attempt — produces no evidence and therefore cannot select an
outcome.

    T0_CONTENT_COMPLETE_READY_FOR_FREEZE_REVIEW
    status: NOT_FROZEN — collection_authorized: false
