# P-022 Stage 3 — the public Rust-default cutover decision

> **What this file is.** The decision surface for #262 Stage 3, frozen *before*
> the implementation it authorizes. It records the contract, the owner rulings
> that amend it, the acceptance predicates and their classification, and — at
> the end — the decision packet #262 requires. It is written to be readable
> against the tree rather than against memory: every claim below is labelled
> with what kind of claim it is.
>
> Stage 3 moves the **default engine**. It does not move the **analysis
> semantics**. The P-022 feature freeze on verdict-changing inference stays in
> force through the cutover.

## Evidence labels

Used verbatim throughout, and never silently exchanged for one another:

| label | meaning |
| --- | --- |
| `REPOSITORY FACT` | true of this tree, checkable by reading or running it |
| `MEASURED OBSERVATION` | produced by an execution recorded here, on a named platform |
| `OWNER RULING` | a decision by the repository owner; not derivable from the tree |
| `DECLARED BEHAVIOR CHANGE` | a deliberate, recorded change in what users observe |
| `DECLARED BOUNDARY` | a difference ruled out of a parity denominator, by policy |
| `INFERENCE` | reasoning from the above; never a substitute for measurement |
| `DEFERRED EVIDENCE` | owed, not taken. **Never** reported as PASS |

## Stage header

```text
STAGE:            P-022 Stage 3 — public Rust-default cutover
BASE SHA:         70189a3de832af51419d0ba6d80572ea7260939d  (origin/main)
OWNER DECISION:   the public default may move to Rust if all NON-PERFORMANCE
                  Stage-3 gates pass
PERFORMANCE:      deferred by owner (see below)
#263:             remains open; remains the performance-baseline tracker
P-037 / A1:       remains blocked until Stage 3 is complete
STAGE 4:          explicitly out of scope — Python distribution removal is a
                  separate, separately reviewable PR after the observation policy
```

## OWNER RULING — performance is deferred

`OWNER RULING`, recorded verbatim as the amendment to #262's evidence policy:

> Performance evidence is deferred by owner for the Stage-3 public-default
> decision. Stage 3 makes no performance claim. #263 remains required before any
> published/reproducible performance claim and remains the performance-baseline
> tracker.

This is an **amendment to the cutover evidence policy**. It is *not* a claim
that the measurements happened, and it is *not* a pass of #262's "Performance
gates" section. #262's prose still says #263 is the evidence prerequisite of the
decision; that sentence is amended here and nowhere else, narrowly, and only for
the Stage-3 public-default decision.

Accordingly, for this decision and no other:

```text
#263 / performance measurements   DEFERRED BY OWNER
physical-host qualification       DEFERRED
startup delta                     NOT MEASURED
end-to-end delta                  NOT MEASURED
peak memory delta                 NOT MEASURED
performance acceptance            NOT CLAIMED
```

Nothing in this note infers that Rust is faster, slower, or equivalent. Any
timing encountered incidentally while taking correctness evidence is **not**
promoted into a performance claim, and no latency budget is invented.

## Non-negotiable boundary

`OWNER RULING` / `REPOSITORY FACT`. Stage 3 changes the default engine, not the
analysis semantics. This change therefore does not: change diagnostic rules or
severity; alter `ConsumesParam`; broaden or narrow Roslyn inference; implement
guarded summaries or any part of P-037; "clean up" Python semantics;
regenerate expectations to hide divergence; or accept a Rust/Python semantic
difference merely because Rust is about to become the default.

An unexplained Rust/Python divergence remains a **bug** until the cutover
decision is complete. There is no silent fallback anywhere.

The three P-037 known-false-positive controls keep their **current** expected
behaviour through this change. Their movement during the cutover would be a
scope-discipline regression, not a fix.

## Acceptance predicates of #262, classified

Every Stage-3 predicate #262 states, and nothing else, classified as
`ALREADY SATISFIED` / `MUST CLOSE NOW` / `DEFERRED BY OWNER — PERFORMANCE ONLY`
/ `NOT A STAGE-3 REQUIREMENT`. No requirement outside the performance section is
deferred; where a genuine prerequisite was missing it is closed rather than
weakened.

### Correctness gates

| # | predicate (#262) | classification |
| --- | --- | --- |
| C1 | #260 fast and broad compare matrices report zero unexplained differences | ALREADY SATISFIED at #260 acceptance; **re-qualified on the Stage-3 candidate tree** (a prior run is not evidence for a changed tree) |
| C2 | five pinned OSS repositories report zero unexplained differences | ALREADY SATISFIED at #260; re-qualified as above |
| C3 | full diagnostic/message/Evidence/SARIF parity green | ALREADY SATISFIED (#259 final acceptance); re-qualified |
| C4 | production OwnIR executable command/output/exit parity (#261) green | ALREADY SATISFIED (#261 closed, PR #347, `206e9c7`); re-qualified, and **extended** by the hygiene tails below |
| C5 | no severity or diagnostic-count drift without a separate Python-first decision | MUST CLOSE NOW — held by the Phase-6 re-qualification |
| C6 | #345 residual `.own`/dev CLI | NOT A STAGE-3 REQUIREMENT (owner decision C-5) |

### Python-first cutover hygiene (recorded by #262 as owed *before* public cutover)

| # | predicate | classification |
| --- | --- | --- |
| H1 | invalid UTF-8: `UnicodeDecodeError` → `OwnIRError` → rc 2 | **MUST CLOSE NOW** |
| H2 | V1 non-finite constants rejected at the JSON door → rc 2, frozen message | **MUST CLOSE NOW** |
| H3 | V2 literal top-level `-0` rejected at the OwnIR input boundary | **MUST CLOSE NOW** |
| H4 | V3 oversized integral version → Version mismatch branch, byte parity | ALREADY SATISFIED (#261 repair-2). Verified, not reopened |
| H5 | V4 Unicode-table representation boundary | DECLARED BOUNDARY, unchanged. Reopen predicate has **not** fired — verified below |

### Reliability gates

| # | predicate | classification |
| --- | --- | --- |
| R1 | malformed OwnIR / malformed source do not panic | MUST CLOSE NOW (re-evaluated against the *production* surfaces) |
| R2 | Rust crashes visible, with reproduction artifacts | ALREADY SATISFIED (#261 fault-injection; Stage-1 D5) — re-qualified |
| R3 | unexpected Rust child exit → public internal-error path, raw status retained | ALREADY SATISFIED (Stage-1 D5, report schema 2) — re-qualified |
| R4 | no Rust failure silently falls back to Python | ALREADY SATISFIED (Stage-1) — re-qualified **on the new default** |
| R5 | deterministic reruns produce identical normalized output | MUST CLOSE NOW |
| R6 | cancellation/interruption tested against the **measured** reference | **MUST CLOSE NOW** — behavioural evidence, not a benchmark; `130` is not invented as universal |
| R7 | memory/resource limits for hostile or very large inputs documented | MUST CLOSE NOW (documented per existing policy; **not** a perf measurement) |
| R8 | Windows and Linux clean-machine paths covered | MUST CLOSE NOW |

### Distribution gates

| # | predicate | classification |
| --- | --- | --- |
| D-a | Rust binary packaged for all supported platforms | **MUST CLOSE NOW** |
| D-b | public `Owen.Cli` install and Action work without undeclared runtimes | **MUST CLOSE NOW** — on the Rust-default path this means *without an undeclared Python runtime* |
| D-c | package upgrade/uninstall/reinstall tested | MUST CLOSE NOW (the release workflow already has the surface) |
| D-d | rollback engine selection documented and tested | **MUST CLOSE NOW** |
| D-e | release workflow tests the actual packed artifact, not a project build | ALREADY SATISFIED in shape (`smoke-test` installs the nupkg) — **extended** to the Rust-default path |

### Performance gates

| # | predicate | classification |
| --- | --- | --- |
| P1..P7 | startup, OwnIR parse, bridge/lowering, analysis, rendering, end-to-end, peak RSS | **DEFERRED BY OWNER — PERFORMANCE ONLY** |

### Acceptance

| # | predicate | classification |
| --- | --- | --- |
| A1 | explicit owner-approved cutover decision exists | this note is the decision surface |
| A2 | Rust is public default only after all gates pass | gated on the above |
| A3 | rollback path tested and documented | MUST CLOSE NOW |
| A4 | observation-period results recorded | MUST CLOSE NOW |
| A5 | Python distribution removal in a later, separately reviewable PR | **Stage 4 — out of scope here** |
| A6 | public Owen install/Action behaviour correct on supported platforms | MUST CLOSE NOW |

## Starting state, verified from the tree

`REPOSITORY FACT`, reconciled at base SHA `70189a3`:

| claim | verified |
| --- | --- |
| #259 final acceptance reached | yes — P-022 status table row, `p022-bridge-verdict-final-acceptance.md` |
| #260 shadow/compare acceptance reached | yes — row 7a |
| #261 production `own-cli` reached | yes — row 7b; PR #347 merged `206e9c7`; #261 closed |
| Stage 1 landed | yes — `--engine` selector, `OWEN_RUST_CORE` locator, D4/D5 |
| Stage 2 landed | yes — `docs/evidence/p022-stage2-census.json`, `tests/test_stage2_dogfood.py` |
| Stage 3 NOT landed | yes — all four launcher surfaces default to Python |
| Python is the public/default reference | yes — `EngineSelection.Default`, `own-check.sh` `engine="python"`, `own-check.ps1` `$Engine = "python"`, `action.yml` `default: "python"` |
| Rust is the repository dogfood default | yes — Stage 2 census, Class-D call sites |
| compare gates still active | yes — `shadow-compare`, `shadow-compare-samples`, `shadow-sweep.yml` |
| #345 not on the cutover path | yes — owner decision C-5 |
| #257 not a Stage-3 blocker | yes — no verified dependency found |

The Stage-3 branch is cut from this base. `REPOSITORY FACT`: at the time of
cutting, the branch had **zero** commits of delta against `origin/main`, so no
P-036/P-037 research work is carried into the cutover.

## D6 — packaged resolution of the Rust core

`REPOSITORY FACT`. `RustCoreLocator` is documented in-tree as the **Stage-1
development** locator, and says so explicitly:

> *"Stage 3's packaged resolution is D6's problem, not this one's — do not solve
> packaging here."*

`INFERENCE` from that fact: making Rust the default without D6 would make a bare
`owen check` on a user's machine exit 2, because `OWEN_RUST_CORE` is unset.
Stage 3 therefore must land D6, and D6 is defined here as:

```text
D6  PACKAGED RESOLUTION
    The `own-cli` binary for the running platform ships INSIDE the Owen.Cli
    payload at a deterministic path, and is resolved from AppContext.BaseDirectory
    exactly the way CoreVendor already resolves the vendored Python core.

    This is packaged resolution, NOT discovery:
      - no PATH lookup
      - no rust/target/{debug,release} probing
      - no "first binary found"
      - no network fetch, no download, no cache population
    OWEN_RUST_CORE keeps its Stage-1 meaning and PRECEDENCE: an explicitly set
    locator still wins, still resolves exactly as before, and its failures are
    still D3.1 configuration errors (exit 2).

    A missing or unusable packaged binary is a VISIBLE configuration/production
    error on the D3.1 path (exit 2) with one actionable diagnostic. It is never
    a reason to run Python.
```

## Rollback contract

`OWNER RULING` + `REPOSITORY FACT`. Rollback is the already-ratified
engine-selection surface, made explicit and tested. It is **not** automatic, and
it is **not** a moved release tag.

```text
no explicit engine selection          -> Rust        (Stage 3 default)
explicit `--engine python` / OWEN_ENGINE=python -> Python (the rollback)
explicit `--engine compare`           -> compare, where the surface exposes it
Rust failure                          -> visible Rust failure, ALWAYS
Rust failure                          -> NEVER an automatic Python success
```

Four states are kept distinct and separately tested; two of them are commonly
conflated, which is why they are named apart:

1. default → Rust;
2. explicit rollback → Python;
3. Rust broken/unavailable **and no rollback requested** → visible failure;
4. Rust broken/unavailable **and Python explicitly selected** → Python runs.

A broken published release is repaired by a **new patch release**. Immutable
release tags are never moved.

## Scope ledger for this change

Allowed and performed: cutover-specific launcher selection; the Python-first
hygiene tails #262 owes; the Rust parity reconciliation those tails require;
packaging; Action wiring; the rollback mechanism, its tests and its docs;
reliability and cancellation tests; Stage-3 evidence; status/doc reconciliation.

Forbidden and not performed: new analysis features; P-037 production code; a
`ConsumesParam` fix; unrelated refactors; performance optimization; #263
implementation; physical-host measurement infrastructure; Stage-4 Python
removal; #345 work; #257 work.

## Decision packet

**Generated, not written.** The packet lives at
[`docs/generated/p022-stage3-packet.md`](../generated/p022-stage3-packet.md) and
is produced by `scripts/stage3_packet.py` from the measurement ledger
[`docs/evidence/p022-stage3-cutover.json`](../evidence/p022-stage3-cutover.json).
No number in it is typed.

`tests/test_stage3_packet.py` holds the ledger to the rules that make the
derivation worth anything — each named for the misreading it stops, and each
mutation-proved: a deferral cannot soften into a claim, performance language
cannot appear outside the deferred fields, an OWED Windows row cannot be filled
in from the Linux one beside it, a bug this change CLOSED cannot be re-listed as
a standing difference, a ratified difference cannot go missing, Python removal
must say Stage 4, and the committed packet must match what the ledger produces.

## Final status

The state these surfaces must agree on, and do:

```text
Stage 1    DONE
Stage 2    DONE
Stage 3    DONE — Rust is public default
Stage 4    NOT STARTED — Python distribution removal remains separate

Python:      explicit rollback/reference available during the observation policy
Rust:        public/default production engine
compare:     retained as development/CI evidence
performance: DEFERRED BY OWNER; no Stage-3 performance claim; #263 remains open
```

P-022 is **not** complete: Stage 4 is open and #263 still owes the baselines
this decision deferred.

With the cutover complete, the P-022 feature freeze on verdict-changing
inference lifts and the **P-037 A1 production gate opens**. It was deliberately
not started here: A1 is a semantic change and this was a cutover, and #262's
guardrails say no semantic cleanup is mixed into one.
