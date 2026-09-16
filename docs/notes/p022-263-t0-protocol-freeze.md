# P-022 / #263 — T0, the pretraining protocol freeze

```text
Status:
  NOT_FROZEN.
  collection_authorized: false
  STRUCTURE RESOLVED. NUMERIC AND HOST SLOTS OPEN.
  MANDATORY UNRESOLVED SLOTS: 12 (T0-completion).
  OPEN NORMATIVE CONFLICTS: none. The #262 ratification blocker was withdrawn
    as a misreading — see T0-3.
  NO CLOCK HAS RUN. NO OBSERVATION EXISTS.
```

**What this is.** The contract that fixes *how numbers will be judged*, before any
number exists. It binds the training collection (step 7), the fit (step 8) and
the decisive campaign (#263-B) alike, because a rule chosen after a look at
training data is not a preregistered rule — it is a preference with a timestamp.

**What this is not.** It is not D7. T0 says how a verdict is computed; D7 later
records *which* exact numbers, candidate, digests and host instances the verdict
was computed from, and adds no analytical decision of its own.

**Authority.** T0-0 revoked the automatic authorisation of the first step-7
collection (`docs/notes/p022-263a-step7-environment-capture.md`). Until this
document is frozen, `collection_authorized` is `false` and no training, first or
decisive collection may run, however ready the hosts are.

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

    (rung, workload, regime)

Engine is not part of the key: it is the two sides of the pair. This is the
ratified four-part cell identity of §2.1 with `engine` projected out, so the pair
exists exactly where both engines have a timed cell.

For each matched pair:

    d_c = log(median(Rust_c)) - log(median(Python_c))
    D   = median_c(d_c)
    R   = exp(D)

`R` is the reported Rust-vs-Python ratio: `R < 1` means Rust is faster.

**Index pairing is forbidden.** `Rust_i / Python_i` for the i-th iteration is not
a paired observation here and may not be computed, reported or gated on.
`run_calibration` shuffles **cells** under a recorded seed and runs a cell's `N`
iterations back to back, so a Rust iteration and a Python iteration with the same
index are separated by an arbitrary stretch of the session. Pairing them would
assert a temporal correspondence the harness does not produce — the "we matched
the fifth Rust run with the third Python run" defect, in a formula.

**The harness is not to be changed to iteration-level A/B interleaving under T0.**
Doing so edits `scripts/perf_baseline.py`, which is one of the two files in the
harness source set, so it moves `measurement_harness_digest 562a7f7232da…` — the
identity steps 4, 5 and 6 were accepted on. That is a new instrument and a
re-evaluation of accepted instrumentation evidence, not a T0 detail.

**An unpaired cell cannot reach the statistic.** A cell whose invocation did not
do the rung's work is not timed at all and the collection is refused
(instrument §2). Therefore a missing side is an admissibility failure — see
T0-4 — and never a pair dropped quietly from `median_c`.

**Recorded consequence.** Cell-level pairing cancels *condition* noise (same
rung, workload, regime, same session, interleaved order). It does not cancel
per-iteration noise, because the data cannot support that claim. No stronger
noise-cancellation property may be asserted for `R`.

---

## T0-2 — Acceptance margins

**FORM RESOLVED. VALUES OPEN.**

A gate FAILs only when both margins are exceeded:

    FAIL(gate)  iff  relative_regression(gate) > M  AND  absolute_regression(gate) > A

Two margins, because neither alone is meaningful: a relative-only rule fails a
`0.20 ms -> 0.24 ms` change that no user can perceive, and an absolute-only rule
is blind to scale.

Semantics, frozen:

| term | definition |
|---|---|
| `relative_regression` | `R - 1` for the gate's cell set, `R` per T0-1 |
| `absolute_regression` | the median over matched pairs of `median(Rust_c) - median(Python_c)`, in the gate's own unit |
| unit, time gates | milliseconds |
| unit, memory gates | bytes of peak RSS |

```yaml
M: UNRESOLVED_OWNER_DECISION          # dimensionless ratio margin
A: UNRESOLVED_OWNER_DECISION          # absolute margin, carries the gate's unit:
                                      # milliseconds for the time gates,
                                      # bytes for the peak RSS gates
M_A_scope: UNRESOLVED_OWNER_DECISION  # see the dimensional constraint below
```

**Dimensional constraint, recorded rather than decided.** `A` carries the gate's
own unit, and the primary set now spans two units — milliseconds and bytes. One
absolute value therefore cannot serve all four gates: a single `A` shared across
time and memory is not a budget the owner has yet to pick, it is not a quantity.
"One pair for all gates" is consequently unavailable for `A` as literally
phrased, and the numeric ruling should be asked in the terms the units allow: one
absolute budget for the time gates and one for the memory gates, with the open
questions being whether `M` — dimensionless, and so unconstrained by this — is
one budget or split, and whether the two gates inside a unit share one `A` or
take one each. No value, and no choice among those readings, is made here.

`M` and `A` derive from the cutover/product budget — what a user may be made to
wait, and how much memory the migration may cost. They may not be derived from
observed Rust-vs-Python results, calibration variance, or training output. Their
relationship to the T0-5 decision limits is itself an open slot, recorded there.

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
| peak RSS | `os.wait4` `ru_maxrss` (POSIX) / job object `PeakProcessMemoryUsed` (Windows), `null` with a reason elsewhere | `DIRECT` where a mechanism exists |
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

**R2 — peak RSS** remains a required resource gate wherever the contract provides
a mechanism, and it carries the same regime dimension as time. `peak_rss_bytes`
is captured on every measured cell, and a cell's key includes its regime, so
memory exists separately for `process-cold` and for `warm` rather than as one
number beside the surface. `warm` memory may not hide inside `process-cold`
memory, or the reverse. Allocation and heap profiling is diagnostic, published for selected
workloads where practical; **a missing allocation profile is neither `INVALID`
nor `FAIL`**, and no instrumentation is added under T0 to obtain one.

**R4 — Option 2, the current observable surface, with no new diagnostic veto
gates.** Catastrophic per-phase caps were considered and rejected: they are an
acceptance policy #262 does not ask for, and they would turn profiling surfaces
back into hidden vetoes. `K`, `B` and `caps_apply_to` are therefore **removed**
from this contract rather than filled — they are not part of it. Should a real
profile later show the need for such a guardrail, it arrives as its own
owner-ratified amendment, not as a silent passenger inside a preregistration.

The primary gate set is therefore exactly **four** independent gates:

```text
launcher-e2e / process-cold / elapsed time   (milliseconds)
launcher-e2e / warm         / elapsed time   (milliseconds)
launcher-e2e / process-cold / peak RSS       (bytes)
launcher-e2e / warm         / peak RSS       (bytes)
```

**No compensation, in either direction**: not between `process-cold` and `warm`,
and not between time and memory. Four gates, each read on its own.

The roll-up over them is the automaton of T0-4, applied without addition:

```text
any gate FAIL            => FAIL
else any NO_DECISION     => NO_DECISION
else                     => PASS
```

**Peak RSS is gated on `launcher-e2e` only.** The instrument captures
`peak_rss_bytes` on every measured cell and those values are **published as
diagnostic evidence**, but a memory number on a diagnostic rung never gates.
Gating memory on the diagnostic rungs would reintroduce through the resource
metric exactly the per-phase veto R4 removed, which is why the scope is named
here rather than left to a reader.

Every other surface in the table is **published, never gating**. A derived view
may inform a reading and may never serve as a gate.

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
             primary gates, T0-2 margins read through the T0-5 limits
             │
             ├─ any gate FAIL ─────────────► FAIL          ─► NO_GO
             ├─ any gate in the gray zone ─► NO_DECISION
             └─ all gates PASS ────────────► PASS          ─► GO
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

---

## T0-5 — Uncertainty rule

**MODEL RESOLVED: deterministic gray zone. LIMITS OPEN.**

    value <= PASS_LIMIT                  => PASS
    value >= FAIL_LIMIT                  => FAIL
    PASS_LIMIT < value < FAIL_LIMIT      => NO_DECISION

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

```yaml
PASS_LIMIT: UNRESOLVED_OWNER_DECISION   # per gate unit; the value at or below which a gate passes
FAIL_LIMIT: UNRESOLVED_OWNER_DECISION   # per gate unit; the value at or above which a gate fails
gray_zone_margin_binding: UNRESOLVED_OWNER_DECISION
# how PASS_LIMIT/FAIL_LIMIT relate to the T0-2 predicate: whether the M/A pair
# IS the FAIL_LIMIT with PASS_LIMIT below it, or the two limits bracket M/A.
# Both readings are consistent with the form; they are not the same contract.
```

The limits are budget quantities. They may not be derived from training results,
calibration variance or any observed comparison.

---

## T0-6 — Invalidation and retry

**SEMANTICS RESOLVED. BUDGET OPEN.**

The unit of invalidation is the **session** — the whole predefined measurement
unit, as the instrument already treats it. A phase, a cell or a workload is never
invalidated, rerun or replaced on its own.

Invalidation fires only on machine-detectable predicates frozen in advance:

- opening or closing noise probe relative IQR above `NOISE_PROBE_MAX_RELATIVE_IQR`
  (0.35);
- drift between opening and closing probes above `NOISE_PROBE_MAX_DRIFT` (0.35);
- reproducibility median change above `REPRODUCIBILITY_MAX_MEDIAN_CHANGE` (0.35);
- a cell that did not do its rung's work, proved by its post-condition;
- a required primary metric that returned `null` or went missing mid-attempt
  (T0-4 case B);
- identity-field drift in the step-7 environment manifest, fields compared whole;
- candidate byte drift within a stratum after collection started.

**A performance result is never an invalidation condition.** Not a slow cell, not
a gray-zone outcome, not a disappointing `R`.

One retry attempt is one full re-collection of the invalidated session on the
same qualified host. Retries are bounded; on exhaustion the outcome is
`NO_DECISION`, never "one more run". Every attempt, including invalidated ones,
is retained as evidence and none is deleted.

```yaml
retry_budget: UNRESOLVED_OWNER_DECISION   # attempts per stratum, integer
```

---

## T0-7 — Host eligibility predicate

**PARTIALLY OPEN — a freeze blocker.**

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
  before the session is eligible (T0-4 case A). On a host where peak RSS has no
  mechanism, the session does not start; it does not start and then fail.

Still unresolved, and each is machine-checkable only once ruled:

```yaml
single_tenant_predicate: UNRESOLVED_OWNER_DECISION      # what a checker asserts
power_policy_requirement: UNRESOLVED_OWNER_DECISION     # per platform
permitted_background: UNRESOLVED_OWNER_DECISION         # what may run during a session
quiesce_procedure: UNRESOLVED_OWNER_DECISION            # and how it is evidenced
manifest_refresh_rule: UNRESOLVED_OWNER_DECISION        # per session or per campaign
```

An incomplete predicate blocks the freeze. It is not an invitation to write down
one drafter's idea of a good benchmark host. Reconnaissance already performed on
a shared developer workstation is **exploratory only**: it may inform the shape of
the predicate and contributes no measurement, no manifest and no qualified host.

---

## T0-8 — Selection and replacement

**RESOLVED.**

1. Qualification runs no Rust-vs-Python benchmark. A host is qualified against the
   predicate and the noise floor, never against how the comparison came out.
2. The first host that passes the predicate, in a predeclared order, becomes the
   host of its stratum.
3. After any outcome-bearing data exists, a host may be replaced only for a
   predeclared environmental failure condition. **A performance outcome is never a
   replacement reason.**
4. Replacement begins with full requalification.
5. Every replacement records: reason, the rule invoked, old identity, new
   identity, time and order. Evidence from the replaced host is retained.

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
the statistic, the pairing unit, `M`, `A`, the gate population, the decision
limits, the uncertainty model, the decision automaton, retry semantics, host
eligibility semantics, or workload selection and replacement rules.

---

## T0-completion

T0 is not frozen while any mandatory slot is unresolved. Until then
`collection_authorized: false`.

| # | slot | section |
|---|---|---|
| 1 | `M` | T0-2 |
| 2 | `A` | T0-2 |
| 3 | `M_A_scope` | T0-2 |
| 4 | `PASS_LIMIT` | T0-5 |
| 5 | `FAIL_LIMIT` | T0-5 |
| 6 | `gray_zone_margin_binding` | T0-5 |
| 7 | `retry_budget` | T0-6 |
| 8 | `single_tenant_predicate` | T0-7 |
| 9 | `power_policy_requirement` | T0-7 |
| 10 | `permitted_background` | T0-7 |
| 11 | `quiesce_procedure` | T0-7 |
| 12 | `manifest_refresh_rule` | T0-7 |

Removed rather than filled, because the acceptance contract does not make the
requirement: `K`, `B`, `caps_apply_to` (R4), and `null_primary_metric_outcome`
(replaced by the three distinct states of T0-4). Closed as a misreading:
ratification of the gate population against #262 (R3).

---

## Hostile review after the rulings

| question | answer |
|---|---|
| see training data, then change the statistic? | **no** — T0-1 resolved, T0-9 forbids revisiting |
| change the pairing definition? | **no** — index pairing named and forbidden |
| change the primary gate population? | **no** — T0-3 resolved under R1/R4; a new gate is an amendment, not an adjustment |
| reintroduce per-phase vetoes quietly? | **no** — the caps were removed from the contract, and a derived view may never gate |
| pick the uncertainty model after the data? | **no** — deterministic gray zone chosen, with its rationale recorded in T0-5 |
| change `M`/`A` or the decision limits? | **yes while unresolved** — the remaining budget exposure, closed by the numeric packet |
| raise the retry budget after a failure? | **yes while unresolved**; once set, bounded, and exhaustion yields NO_DECISION |
| replace a host because the result is unpleasant? | **no** — T0-8 rules 3 and 5 |
| can a missing or null primary metric yield PASS? | **no** — structurally, in all three T0-4 states |
| can a host with no mechanism for a required metric start a session? | **no** — T0-7 eligibility, T0-4 case A |
| can anyone start collecting because hosts and binding are ready? | **no** — T0-0 revoked that; `collection_authorized: false` |
| can one evidence set yield both PASS and FAIL under two admissible readings? | **no** once the limits are set — the automaton is a function of evidence; **yes while `PASS_LIMIT`/`FAIL_LIMIT` are empty** |

Three "yes" answers remain, all of them the same thing: the budget numbers are
not chosen yet. None is a structural hole, and none may be closed by looking at
data.

    T0_SKELETON_READY_FOR_NUMERIC_RULINGS
    status: NOT_FROZEN — collection_authorized: false
