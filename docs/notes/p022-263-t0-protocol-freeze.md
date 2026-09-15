# P-022 / #263 — T0, the pretraining protocol freeze

```text
Status:
  NOT_FROZEN.
  collection_authorized: false
  MANDATORY UNRESOLVED SLOTS: 9 (T0-completion).
  OPEN NORMATIVE CONFLICT: 1, against #262 (T0-3).
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
owner.

---

## T0-1 — Statistic and pairing unit

**FROZEN.**

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

**FORM FROZEN. VALUES UNRESOLVED.**

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
A: UNRESOLVED_OWNER_DECISION          # absolute margin, in the gate's unit
M_A_scope: UNRESOLVED_OWNER_DECISION  # one pair for all gates, or per-gate pairs
```

`M` and `A` derive from the cutover/product budget — what a user may be made to
wait, and how much memory the migration may cost. They may not be derived from
observed Rust-vs-Python results, calibration variance, or training output.

---

## T0-3 — Gate population and aggregation

**BLOCKED. `NORMATIVE_RATIFICATION_REQUIRED_AGAINST_262`.**

#263-A must not silently narrow #263's acceptance (instrument §1), so the gate
population is not T0's to settle. What T0 can do is state the conflict exactly.

### The authoritative list, and what is actually observable

#262's performance gates name seven phases. The instrument measures a ladder of
real production invocations and records each as the composed interval it is:

| #262 gate phase | observable as | standalone number? |
|---|---|---|
| process startup | `core-usage`, composed over `process-startup-core` + `cli-argv-parse` + `cli-usage-refusal` | **no** — a *lower bound* on core startup; `process-startup-launcher` is separate and lives inside `launcher-e2e` |
| OwnIR parse | `core-parse-refused - core-usage` | **no** — a derived bound, valid only under an assumption the instrument never measures |
| bridge/lowering | member of `core-full-*` | **no** — not separately observable (§14.1) |
| analysis | member of `core-full-*` | **no** — not separately observable (§14.1) |
| CLI/SARIF rendering | `core-full-sarif - core-full-human` | **no** — a renderer *difference*, which is not rendering in isolation |
| end-to-end C# project/solution run | `launcher-e2e` | **yes** |
| peak RSS / allocations where practical | RSS by named mechanism per platform | **RSS yes**; allocations **not captured** (§14.2) |

Two of #262's seven gate phases yield a standalone gateable number. One yields a
bound. Four exist only as derived views, which §2 forbids presenting as
measurements.

### The proposed reshape, and the three conflicts it raises

Proposed primary gates: process startup, cold E2E, warm E2E, peak RSS.
Proposed diagnostic-only: OwnIR parse, bridge/lowering, analysis, rendering,
frontend extraction.

- **C1 — acceptance surface.** Moving parse, bridge/lowering, analysis and
  rendering out of the gating set changes #262's acceptance surface. Sound
  engineering — one user-visible effect should not be gated four times — but it
  is a normative change, and instrument §1 exists precisely to stop it happening
  by omission. **Requires ratification against #262.**
- **C2 — "process startup" is not one number.** As a primary gate it can mean
  `core-usage` (a bound on the child's startup) or `process-startup-launcher`
  (what a user waits for), and §2 keeps the two deliberately unmerged. Which one
  gates is undefined. **Requires a ruling, then ratification.**
- **C3 — three of the five diagnostics do not exist.** bridge/lowering, analysis
  and launcher-scoped extraction are not separately observable; parse and
  rendering exist only as derived bound and difference. A diagnostic list must be
  written against observables, or it manufactures several metrics out of one
  interval — the defect §2 records as `launcher-extract` withdrawn.
- **C4 — allocations.** #262's phrasing is "peak RSS/allocations where
  practical"; allocations are not captured. Whether "where practical" already
  discharges this must be recorded explicitly, not assumed.

### Catastrophic-regression caps

A diagnostic metric does not veto the cutover, but a diagnostic surface that
collapses should not pass silently either.

```yaml
K: UNRESOLVED_OWNER_DECISION   # per-phase ratio cap, dimensionless
B: UNRESOLVED_OWNER_DECISION   # per-phase absolute cap, in the phase's unit
caps_apply_to: UNRESOLVED_OWNER_DECISION   # which observable surfaces carry a cap
```

A cap fires only when both are exceeded, on the same two-margin logic as T0-2.

**Normative, independent of the ratification:** a derived view (`core-parse-refused
- core-usage`, `core-full-sarif - core-full-human`) may inform a reading and may
never serve as a gate or a cap, and no two metrics may be manufactured from one
observable interval.

---

## T0-4 — Decision automaton

**STRUCTURE FROZEN. ONE SLOT.**

Terminal states are exactly four, and the reading is a function of evidence, not
prose:

```text
admissibility (T0-6 invalidation predicates)
   │
   ├─ violated ─────────────────────────────► INVALID
   │
   └─ clean
        │
        required primary metric missing or null
        │
        ├─ yes ──────────────────────────────► INVALID or NO_DECISION   (never PASS)
        │
        └─ no
             │
             primary gates, T0-2 margins under the T0-5 uncertainty rule
             │
             ├─ regression proven ────────────► FAIL      ─► NO_GO
             ├─ neither proven ───────────────► NO_DECISION
             └─ non-inferiority proven
                  │
                  catastrophic caps (T0-3)
                  ├─ violated ────────────────► FAIL      ─► NO_GO
                  └─ clean ───────────────────► PASS      ─► GO
```

`INVALID` and `NO_DECISION` both map to `NO_DECISION` at the cutover level: no
evidence, no verdict. They are kept apart because they mean different things —
`INVALID` says the measurement did not happen properly, `NO_DECISION` says it
happened and did not resolve.

**A missing primary metric may never read as "no regression found".** Peak RSS is
the live case: §9 emits `null` with a reason where no mechanism exists, so if RSS
is a primary gate, a Job Object that did not answer on Windows must not become a
silent pass.

```yaml
null_primary_metric_outcome: UNRESOLVED_OWNER_DECISION
# INVALID  — treat an unmeasurable primary gate as a broken measurement, retry-eligible
# NO_DECISION — treat it as measured-but-unresolved, not retry-eligible
```

---

## T0-5 — Uncertainty rule

**OPTIONS STATED. MODEL UNRESOLVED.**

Without an uncertainty rule, `1.0999 -> PASS` and `1.1001 -> FAIL` become
metaphysics on a machine whose own floor tolerates 0.35 relative IQR.

Cell count bounds the choice: up to `5 rungs x 13 decisive workloads x 2 regimes`
= 130 cell pairs per platform, less whatever `_rung_accepts` rejects, and less
again if the gate population shrinks to primary surfaces only.

| | Option A — bootstrap over paired cells | Option B — deterministic gray zone |
|---|---|---|
| shape | resample cell pairs, preregistered confidence level; PASS if the upper bound ≤ margin, FAIL if the lower bound > margin, else NO_DECISION | fixed `PASS_LIMIT` / `FAIL_LIMIT`; between them, NO_DECISION |
| reproducibility | recomputable from retained raw, but only if resampling unit, resample count and RNG seed are frozen too — otherwise the interval is itself a degree of freedom | trivially recomputable, no RNG |
| few cells | interval widens honestly; a narrow gate population can make NO_DECISION the usual outcome | insensitive to sample size — a 3-cell result and a 100-cell result read identically |
| retry semantics | a wide interval is **not** an invalid run; if it were, retry-until-narrow is rerun-until-pass | same; the gray zone is an outcome, not a retry trigger |
| machine-checkable | yes, once every parameter is frozen | yes, the simplest possible predicate |
| post-hoc exposure | low if frozen; the live risk is choosing the confidence level after seeing the width | low; the limits must come from the budget, and they overlap T0-2 unless defined as a bracket around `M`/`A` |

```yaml
uncertainty_model: UNRESOLVED_OWNER_DECISION          # A or B
confidence_level: UNRESOLVED_OWNER_DECISION           # if A
bootstrap_unit_resamples_seed: UNRESOLVED_OWNER_DECISION  # if A; all three, frozen
gray_zone_limits: UNRESOLVED_OWNER_DECISION           # if B; PASS_LIMIT and FAIL_LIMIT
```

---

## T0-6 — Invalidation and retry

**SEMANTICS FROZEN. BUDGET UNRESOLVED.**

The unit of invalidation is the **session** — the whole predefined measurement
unit, as the instrument already treats it. A phase, a cell or a workload is never
invalidated, rerun or replaced on its own.

Invalidation fires only on machine-detectable predicates frozen in advance:

- opening or closing noise probe relative IQR above `NOISE_PROBE_MAX_RELATIVE_IQR`
  (0.35);
- drift between opening and closing probes above `NOISE_PROBE_MAX_DRIFT` (0.35);
- reproducibility median change above `REPRODUCIBILITY_MAX_MEDIAN_CHANGE` (0.35);
- a cell that did not do its rung's work, proved by its post-condition;
- identity-field drift in the step-7 environment manifest, fields compared whole;
- candidate byte drift within a stratum after collection started.

**A performance result is never an invalidation condition.** Not a slow cell, not
a wide interval, not a disappointing `R`.

One retry attempt is one full re-collection of the invalidated session on the
same qualified host. Retries are bounded; on exhaustion the outcome is
`NO_DECISION`, never "one more run". Every attempt, including invalidated ones,
is retained as evidence and none is deleted.

```yaml
retry_budget: UNRESOLVED_OWNER_DECISION   # attempts per stratum, integer
```

---

## T0-7 — Host eligibility predicate

**PARTIALLY NORMATIVE. INCOMPLETE — a freeze blocker.**

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
  identical across every run of that stratum.

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

**FROZEN.**

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

**FROZEN.**

Training may derive **`N` and nothing else**, by the already-ratified rule: the
ladder `[5, 15, 45]`, `G = [1, 10]`, per-stratum admissible sets
`Q_p = { N : W_p(N) <= (1+G) * min_N W_p(N) }`, selection = the smallest rung in
`Q_linux ∩ Q_windows`, and `NO_COMMON_N` is a stop with no fallback rung.

Training may not change, and seeing training output grants no licence to revisit:
the statistic, the pairing unit, `M`, `A`, the gate population, `K`, `B`, the
uncertainty model and its parameters, the decision automaton, retry semantics,
host eligibility semantics, or workload selection and replacement rules.

---

## T0-completion

T0 is not frozen while any mandatory slot is unresolved or any normative conflict
is open. Until then `collection_authorized: false`.

| # | slot | section |
|---|---|---|
| 1 | `M` | T0-2 |
| 2 | `A` | T0-2 |
| 3 | `M_A_scope` | T0-2 |
| 4 | `K`, `B`, `caps_apply_to` | T0-3 |
| 5 | `null_primary_metric_outcome` | T0-4 |
| 6 | `uncertainty_model` + its parameters | T0-5 |
| 7 | `retry_budget` | T0-6 |
| 8 | host predicate slots (5) | T0-7 |
| 9 | ratification of the gate population against #262, incl. C2's "which startup" | T0-3 |

---

## Hostile review of this skeleton

| question | answer under T0 as drafted |
|---|---|
| see training data, then change the statistic? | **no** — T0-1 frozen, T0-9 forbids revisiting |
| change the pairing definition? | **no** — T0-1 frozen, index pairing named and forbidden |
| change `M`/`A`? | **no once ruled** — but **yes while unresolved**, which is why the freeze is blocked |
| change the primary gate population? | **yes today** — C1/C2 open; closes only by ratification against #262 |
| change `K`/`B`? | **yes while unresolved** |
| pick the uncertainty model after the data? | **yes while unresolved** — the single largest post-hoc exposure left |
| raise the retry budget after a failure? | **no once ruled** — bounded, exhaustion yields NO_DECISION |
| replace a host because the result is unpleasant? | **no** — T0-8 rules 3 and 5 |
| can a missing or null primary metric yield PASS? | **no** — T0-4, structurally |
| can anyone start collecting because hosts and binding are ready? | **no** — T0-0 revoked that; `collection_authorized: false` |
| can one evidence set yield both PASS and FAIL under two admissible readings? | **yes while T0-3 and T0-5 are open**; **no** once both are closed, since the automaton is then a function |

Five "yes" answers remain. Every one of them is an empty slot or the open #262
conflict — none can be closed by drafting, and none may be closed by looking at
data.

    T0_NOT_FREEZABLE — until the table above is all "no".
