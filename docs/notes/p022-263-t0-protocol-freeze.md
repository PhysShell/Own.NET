# P-022 / #263 — T0, the pretraining protocol freeze

```text
Status:
  NOT_FROZEN.
  collection_authorized: false
  CONTENT COMPLETE. HOSTILE FREEZE REVIEW PENDING.
  MANDATORY UNRESOLVED SLOTS: 0 (T0-completion).
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

**RESOLVED (R5, R6, R7). No open value.**

Two coordinates, never collapsed into a score:

| term | definition |
|---|---|
| `relative_regression` | `R - 1` for the gate's cell set, `R` per T0-1 |
| `absolute_regression` | the median over matched pairs of `median(Rust_c) - median(Python_c)`, in the gate's own unit |
| unit, time gates | milliseconds — the instrument records `perf_counter_ns`, so the conversion belongs to the reading, never to the evidence |
| unit, memory gates | bytes of peak RSS, after the instrument's own `ru_maxrss` unit normalisation (kilobytes on Linux, bytes on macOS/BSD) |

Two margins, because neither alone is meaningful: a relative-only rule fails a
`0.20 ms -> 0.24 ms` change that no user can perceive, and an absolute-only rule
is blind to scale.

Each gate carries **two pairs** of budgets — one pair that admits a pass, one
pair that compels a failure — and the decision rule over them is T0-5:

```yaml
# R6 — both primary elapsed-time gates
#      launcher-e2e / process-cold / elapsed
#      launcher-e2e / warm         / elapsed
M_pass_time: 0.05          # +5 %
A_pass_time: 50            # milliseconds
M_fail_time: 0.10          # +10 %
A_fail_time: 100           # milliseconds

# R7 — both primary peak-RSS gates
#      launcher-e2e / process-cold / peak RSS
#      launcher-e2e / warm         / peak RSS
M_pass_rss:  0.10          # +10 %
A_pass_rss:  33554432      # bytes, 32 MiB
M_fail_rss:  0.20          # +20 %
A_fail_rss:  67108864      # bytes, 64 MiB
```

Required of every gate, and true of both sets above:

    M_pass < M_fail
    A_pass < A_fail

Both regimes of a resource share that resource's budgets — not because
`process-cold` and `warm` are the same thing, but because the product price of
making a user wait is the same in either. Time and memory do **not** share
budgets: a single absolute value cannot span milliseconds and bytes, and a shared
relative budget would be a tidy symmetry bought with meaning. This is what
replaces the old `M`, `A` and `M_A_scope`: eight named per-resource budgets, with
no scope left ambiguous.

These budgets come from the cutover/product price of latency and memory. They may
not be derived from observed Rust-vs-Python results, calibration variance, or
training output — and none of the eight was.

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
             each of the four primary gates, by the two-dimensional rule of
             T0-5 over the T0-2 budgets
             │
             ├─ any gate FAIL ─────────────► FAIL          ─► NO_GO
             ├─ any gate NO_DECISION ──────► NO_DECISION
             └─ all four gates PASS ───────► PASS          ─► GO
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

**RESOLVED (R5): a deterministic gray zone in two dimensions.**

The gray zone is defined on the same two coordinates the margins are, and no
synthetic scalar score is constructed from them. Per gate:

```text
PASS          iff  relative_regression <= M_pass
               OR  absolute_regression <= A_pass

FAIL          iff  relative_regression >= M_fail
              AND  absolute_regression >= A_fail

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
requires `relative_regression <= M_pass < M_fail`, which contradicts `FAIL`'s
`relative_regression >= M_fail`; `PASS` via the absolute coordinate contradicts
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

The zone's boundaries are the eight budgets of T0-2 and nothing else: there is no
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
- reproducibility median change above `REPRODUCIBILITY_MAX_MEDIAN_CHANGE` (0.35);
- a cell that did not do its rung's work, proved by its post-condition;
- a required primary metric that returned `null` or went missing mid-attempt
  (T0-4 case B);
- identity-field drift in the step-7 environment manifest, fields compared whole,
  on the post-session recheck (R9);
- candidate byte drift within a stratum after collection started.

**A performance result is never an invalidation condition.** Not a slow cell, not
a gray-zone outcome, not a disappointing `R`. Every predicate above is
machine-detected, so no operator chooses to invalidate a session.

One retry attempt is one full re-collection of the invalidated session on the
same qualified host. Every attempt, including invalidated ones, is retained as
evidence and none is deleted.

```yaml
retry_budget: 1        # R8
```

Read literally:

    1 initial attempt
    + at most 1 full-session retry after INVALID
    = at most 2 attempts per stratum

After a second `INVALID`, the outcome is `NO_DECISION`. There is no third throw
of the coin. One retry survives a genuine one-off environmental failure; a larger
budget would turn the campaign into a machine that runs until the infrastructure
eventually cooperates.

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
  before the session is eligible (T0-4 case A). On a host where peak RSS has no
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
the statistic, the pairing unit, any of the eight per-resource budgets, the gate
population, the two-dimensional decision rule, the decision automaton, retry
semantics and budget, manifest refresh, host eligibility semantics, or workload
selection and replacement rules.

---

## T0-completion

**No `UNRESOLVED_OWNER_DECISION` slot remains.** Every value this contract needs
is now in it:

| what | where | ruling |
|---|---|---|
| eight per-resource budgets | T0-2 | R6, R7 |
| the two-dimensional decision rule | T0-5 | R5 |
| `retry_budget: 1` | T0-6 | R8 |
| `manifest_refresh_rule: per session` | T0-6 | R9 |
| single-tenancy, in two evidence classes | T0-7 | R10 |
| power policy, per platform | T0-7 | R11 |
| permitted background | T0-7 | R12 |
| quiesce procedure | T0-7 | R13 |

Removed rather than filled, because the acceptance contract does not make the
requirement: `K`, `B`, `caps_apply_to` (R4); `null_primary_metric_outcome`
(replaced by the three distinct states of T0-4); and `PASS_LIMIT`, `FAIL_LIMIT`,
`gray_zone_margin_binding` (R5 — symptoms of a scalar model that did not match the
two coordinates the margins are defined on). Superseded: `M`, `A` and `M_A_scope`,
by the eight typed per-resource budgets. Closed as a misreading: ratification of
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
| can one evidence set yield both PASS and FAIL under two admissible readings? | **no** — per gate the two conditions are mutually exclusive by `M_pass < M_fail` and `A_pass < A_fail`, and the roll-up is a total function of the four gate outcomes |
| does the declaration of single tenancy masquerade as proof? | **no** — provisioning evidence and runtime invariants are separated, and only the latter is called machine-verified |

No "yes" answer remains that a decision could close. The one permitted item — a
repeated quiesce attempt — produces no evidence and therefore cannot select an
outcome.

    T0_CONTENT_COMPLETE_READY_FOR_FREEZE_REVIEW
    status: NOT_FROZEN — collection_authorized: false
