# P-038 — Boundary transition witness

- **Status:** accepted — experiment ratified; product not proposed.
- **Question:** does an unobserved production transition carry information that local point coverage and mutation adequacy do not?
- **Scope:** experiment only. No tool is proposed for adoption, no ARCH rule is added, no architecture-gate verdict can move because of this proposal, and the first slice requires no runtime collector.
- **Split:** Own.NET owns architecture coordinates and static facts; OwnAudit owns the join, classification, baseline/diff, and report, following P-032.

## 0. Adjacent work and the boundary this moves

This proposal consumes rather than duplicates:

- P-023 (`Own.Arch`) for the architecture coordinate system;
- P-032 for `own.arch.facts.*`, `own.findings/v1`, and the Own.NET producer / OwnAudit consumer split;
- P-015 reachability evidence for evidence-shape precedent, not inputs or outputs;
- P-012 / LeakFixMine for corpus discovery, SZZ causality, bias defence, matched controls, and the existing static-tier ladder;
- the retention runtime-witness docs for the rule that observation-pipeline limitations must never silently become verdicts;
- LeakyOracle for the synthetic positive-control pattern;
- tech-debt register N4 for schema timing;
- OwnAudit `arch/graph.py`, `arch/drift.py`, and `arch/rules.json` for the consumer-side reporting surface.

### 0.1 Reconciliation with P-023

P-023 explicitly excludes test-coverage drift from the architecture guard. P-038 does not reverse that decision.

> **P-038 adds no coverage semantics to Own.Arch evaluation, contributes no ARCH finding codes, and can never move an architecture gate verdict. Architecture facts are used only as a coordinate system for a separate test-evidence overlay owned by OwnAudit. Nothing about coverage enters `rules.yaml`, the baseline ratchet, or the evaluator.**

## 1. Construct

A mutant is a point. The object of interest here is a transition.

Every component in a chain can be covered and locally mutation-adequate while the production chain itself never executes as a path, because tests substitute the far side at each seam. The candidate defect class is therefore boundary-shaped: serialization, protocol shape, lifecycle, ordering, reconnection, transaction semantics, configuration, and environment.

The first adjudicating experiment is deliberately narrower than that list: **in-process executable call transitions only**.

## 2. Architecture edge != executable transition

Architecture edges include `ProjectReference`, package dependency, type dependency, forbidden-API dependency, inheritance-like type relations, and namespace relations. Not all have execution semantics.

An architecture edge therefore has `0..N` executable boundary sites. Only a site can be witnessed. An edge with no executable site in the extractor's modeled transition domain is not a transition gap.

## 3. Data model: three levels, two identity domains

Static extraction and runtime observation are related but not identical identity domains.

```text
ArchitectureEdge
  edge_id
  static_site_resolution:
    resolved | none_in_model | indeterminate
  static_sites:
    - site_id
      caller
      callsite
      target
      static_test_proxy

RuntimeTransition
  runtime_transition_id
  edge_id
  matched_site_id: site_id | null
  site_match:
    matched | runtime_only | ambiguous
  runtime_observation:
    observed | not_observed | indeterminate
```

`none_in_model` means exhaustive static extraction found no executable sites **within the transition domain that extractor models**. It never means the edge can have no runtime transition.

`indeterminate` means the static extractor may not assert absence.

`resolved` means one or more static sites were identified.

A runtime-only transition is valid evidence of static-extraction incompleteness. It is reported in full but excluded from the primary site-level adjudication because the local static comparator vector cannot be defined reproducibly for a site that does not statically exist. `ambiguous` is likewise never silently forced onto one site.

### 3.1 `static_test_proxy`

The static proxy is separate from site existence. Its values are:

```text
likely_witnessed | likely_unwitnessed | indeterminate
```

Its exact operational predicate must be frozen before the funding gate runs and implemented exactly as frozen. It must be allowed to abstain; `indeterminate` is first-class and must not be folded into either side.

### 3.2 Absence requires proof the camera was on

A positive observation is cheap epistemically:

```text
transition record observed -> transition occurred
```

A negative observation is not:

```text
no transition record != transition did not occur
```

### 3.3 Binding rule for `not_observed`

`not_observed` is admissible only when all of the following hold:

- the static site was instrumented;
- the collector supports the transition kind;
- the declared test domain completed;
- collection completed without event loss;
- per-test attribution is unambiguous.

Otherwise the result is `indeterminate`.

Admissible attribution means per-test isolation or demonstrably propagated test context. Timestamp-only attribution is not sufficient for parallel tests or background work crossing the transition after the originating test has completed.

A sampling profiler can establish `observed`; it can never establish `not_observed`. The negative class requires exhaustive instrumentation or an explicit completeness guarantee over the in-scope transition kind.

Stryker.NET is a baseline competitor, not the transition collector: mutation-point coverage is not an arbitrary dynamic call graph. Its exact per-test semantics must be re-verified against the version used before execution.

### 3.4 Static sites and runtime transitions have separate identity

A runtime record joins to a static `site_id` only when the transition can be matched to that static site. Runtime-only and ambiguous transitions remain first-class evidence rather than being coerced onto a site.

### 3.5 `site_id` stability is revision-scoped

`site_id` is stable across producers and collectors for the **same source revision**.

Cross-revision site equivalence is not defined by P-038. Deciding whether two callsites are "the same site" after refactoring is a separate research problem and is deliberately out of scope.

## 4. Producer split

| Producer | Emits |
|---|---|
| Own.NET, build-free / semantic tier | architecture edges; `static_site_resolution`; static sites with revision-scoped `site_id`; `static_test_proxy`. No runtime claim. |
| Runtime collector, executed tier | transition records with completeness and attribution provenance. |
| OwnAudit | join, classification, baseline/diff, reporting. |

### 4.1 Evidence provenance

Runtime evidence must carry enough provenance to defend a positive observation and, for a negative observation, the completeness conditions above. At minimum the record family must bind source revision, edge/site identity where available, test identity, collector identity/version, transition kind, attribution mode, completeness state, and event-loss state.

If any field needed to defend `not_observed` is unavailable, the value degrades to `indeterminate`.

### 4.2 No scalar score

A ratio and a bare gap list are both gameable by one enormous end-to-end test that crosses every boundary once. Goodhart is not defeated by choosing a list over a scalar.

The defence is provenance: the report must be able to show, for example, that most witnessed transitions depend on one test. Neither a scalar nor an unannotated gap list can express that.

## 5. Experiment ladder

### 5.1 Calibration / feasibility gate

Build a LeakyOracle-style repository where a boundary-class defect is real, the suite is green and mock-heavy, line coverage is high, and mutation score is high. The static detector must identify the constructed case.

Failure kills the implementation or proxy definition, not the research hypothesis.

### 5.2 Cheap funding gate: static re-analysis over the existing corpus

LeakFixMine already supplies SZZ-confirmed cases, historical coordinates, and corpus metadata. The funding gate still requires checking out pre-fix revisions and running the static proxy over production and test sources; it is source analysis, not a SQL query.

The quantity is:

```text
P(proxy-gap | defect case)
vs
P(proxy-gap | matched control)
```

never the distribution of defect cases alone.

Measurement is performed on the **pre-fix revision** to avoid post-treatment leakage from tests added by the fix.

Controls are "matched controls", never "clean" or "non-defective" sites. Under nondifferential contamination, hidden defect history is expected to attenuate association toward the null; the direction is not guaranteed if contamination depends on proxy state or boundary properties.

A null result here is a budget stop-rule: do not fund dynamic transition evidence. It is not falsification of a runtime-transition hypothesis.

#### 5.2.1 Unit of analysis

Pre-registered for the funding gate: **case-level**.

```text
one defect = one observation
exposure =
  any relevant site is a proxy-gap
  | all relevant sites likely_witnessed
  | indeterminate
```

A site-level design is permissible only with clustering by fix and repository, and only if the causal-region -> `site_id` mapping is frozen before any witness outcome is inspected.

### 5.3 Adjudicating experiment

The executed tier uses a small curated runnable set. Per static site the comparator vector is local:

- caller covered?;
- callee covered?;
- callsite covered?;
- caller mutants: killed / survived / no-coverage;
- callee mutants: killed / survived / no-coverage;
- endpoints co-covered by the same test?;
- transition: observed / not_observed / indeterminate.

Repository-wide mutation scores are not substitutes for these local comparators.

The first adjudicating experiment covers only **statically resolved in-process call transitions for which exhaustive observation is technically available**. RPC, message, transaction, event, and process-boundary transitions are later taxonomies, justified only if the narrow experiment finds useful signal.

Runtime-only and ambiguous transitions are excluded from the primary analysis and reported alongside it.

#### 5.3.1 Attrition and sensitivity

Before any executed outcomes are inspected:

- report `indeterminate` rates overall, for cases, for controls, and by site kind;
- report `runtime_only` and `ambiguous` rates;
- fix a differential-indeterminacy threshold above which the result is `INCONCLUSIVE` regardless of the complete-case estimate;
- do not report complete-case analysis alone;
- use a pre-specified adversarial-bounds sensitivity analysis: assign every indeterminate case/control in the direction most favourable to H1 and then most favourable to H0. If the resulting bounds straddle the useful-effect floor, the result is `INCONCLUSIVE`.

#### 5.3.2 Per-test -> per-site aggregation

The declared test domain is the **full green suite at that revision**, never a hand-picked set of "relevant tests".

```text
observed:
  at least one attributable transition record for that site_id

not_observed:
  no transition record
  AND all §3.3 completeness conditions hold over the whole test domain

indeterminate:
  otherwise
```

### 5.4.0 Primary estimand

The primary estimand is the adjusted association between `not_observed` transition status and defect status among **statically resolved in-process call sites** for which:

- the local comparator vector is defined;
- the full green suite is the observed test domain;
- collector completeness is established;
- per-test attribution is admissible.

`runtime_only` and `ambiguous` transitions are disagreement evidence and an external-validity diagnostic. They do not enter the primary estimand.

The primary result therefore does not support or refute the hypothesis for a large excluded runtime-only or ambiguous population. Narrow the estimand rather than pretending the first experiment speaks for every production transition.

### 5.4 Hypothesis

**H0:** conditional on the local comparator vector, transition observation has no practically meaningful additional association with defect status within the §5.4.0 population.

**H1:** conditional on the same vector and within the same population, sites whose transition is `not_observed` are more strongly associated with escaped defects.

This is association, not incidence. The retrospective matched case/control design yields an adjusted odds ratio within matched strata. Out-of-sample prediction is not claimed.

### 5.4.1 Mechanical decision rule

For a one-sided H1 (`OR > 1`) against a pre-registered useful-effect floor:

```text
POSITIVE
  the pre-registered interval supports an effect at or above
  the useful-effect floor, and attrition/sensitivity rules do not force
  INCONCLUSIVE

NEGATIVE
  the pre-registered interval excludes every effect at or above
  the useful-effect floor, and attrition/sensitivity rules do not force
  INCONCLUSIVE

INCONCLUSIVE
  everything else
```

The useful-effect floor is fixed before executed data are inspected, from the effect size that would justify building and maintaining a product. It is not chosen from a significance convention and not after seeing the estimate.

`INCONCLUSIVE` does not license `CLOSED` as a negative scientific result.

### 5.4.2 Frozen before executed data

Before §5.3 outcomes are inspected, preregister:

- the primary estimator: conditional logistic regression preserving matched strata, or an exact conditional method under a pre-specified sparsity rule;
- comparator coding, including three-valued mutation states and coverage representation;
- the interval/precision procedure and equivalence test against the useful-effect floor;
- complete/quasi-complete separation handling;
- the differential-indeterminacy threshold;
- the exact adversarial assignment used by §5.3.1;
- the §5.4.0 estimand population in the run's own preregistration.

Pooling matched sets into one unconditional fit discards the design and is not admissible.

## 6. Analysis tier

LeakFixMine's existing ladder is syntactic -> semantic -> interproc, all static. Runtime transition evidence requires an executed tier: restore, build, run the full green suite, and collect attributable transition records.

At this tier, historical build success is not merely degradation; without a runnable revision the observation collapses. The corpus-wide mining target therefore cannot back the executed tier. The adjudicating experiment uses a small curated runnable set.

## 7. First slice

The first slice writes **no runtime collector**.

It asks only whether a proxy-defined candidate population exists in already-owned repositories / the existing corpus. If cases satisfying the local point/mutation conditions while appearing to preserve a static transition gap are almost absent, stop and record the decision.

## 8. Schema

Schema timing is governed by tech-debt register N4. A machine-readable schema is co-designed when a second hand-written type set appears and generated from that authority; no standalone JSON-schema validator is added to the zero-dependency core merely because this proposal exists.

Whether the trigger has already fired for existing `own.arch.facts/*` and `own.findings/v1` contracts is separate from P-038.

## 9. Non-goals and closure

- No mock linter, mock-surface ratio, constructor-explosion rule, tautology detector, or choreography score.
- No coverage semantics in Own.Arch.
- No ARCH codes and no architecture-gate verdict effect.
- No scalar KPI.
- No transition taxonomy beyond in-process calls in the first adjudicating experiment.
- No cross-revision site identity.
- No incidence claim and no predictive claim.
- Not a coverage replacement.
- No second research arm.

A failed calibration/funding/adjudication path does **not** delete this document. It becomes a decision record, for example:

```text
CLOSED — calibration/definition failed
CLOSED — static funding gate showed no useful signal; executed experiment not funded
CLOSED — useful additional association excluded by the pre-registered decision rule
```

`INCONCLUSIVE` records that the executed instrument could not adjudicate and does not masquerade as a negative result.

## 10. Risks

| Risk | Mitigation |
|---|---|
| Proxy manufactures signal by never abstaining | `indeterminate` is first-class (§3.1). |
| Collector false negatives become gaps | §3.3 completeness rule; sampling collectors excluded from negative class. |
| Parallel/async tests mis-attribute transitions | §3.3 attribution rule; ambiguity -> `indeterminate`. |
| Runtime-only transitions forced onto static sites | separate identity domains and explicit `site_match` (§3.4). |
| Cross-revision identity research creeps in | explicitly out of scope (§3.5). |
| Test-domain cherry-picking | full green suite (§5.3.2). |
| Small-n analysis degrees of freedom | preregister estimator, coding, precision, separation (§5.4.2). |
| Underpowered study written as refutation | three outcomes and useful-effect floor (§5.4.1). |
| Missing-data model chosen after seeing the gap | adversarial bounds fixed before outcomes (§5.3.1). |
| Pseudoreplication | case-level funding design / frozen mapping (§5.2.1). |
| Matching discarded | matched-strata estimator (§5.4.2). |
| Global metrics hide local NoCoverage | all comparators local (§5.3). |
| Executed-tier corpus collapses | accepted; executed tier is curated, not corpus-scale (§6). |
| Per-test tooling is rebuilt from scratch | needing a bespoke collector from scratch is grounds to stop. |
| P-023 scope is re-entered | §0.1 is binding. |
| Negative result is rediscovered later | `CLOSED` decision record, never deletion. |
