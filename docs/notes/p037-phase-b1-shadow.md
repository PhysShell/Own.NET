# P-037 Phase B1: the guarded shadow read (pre-registered)

> Status: **PRE-REGISTERED and AMENDED by owner review (§G). Implementation is
> authorized from the amendment commit on; the boundaries do not move after
> it.**
>
> This contract is committed before any implementation, so the result is
> judged against it rather than an impression afterwards.
>
> - Governance: `docs/notes/p037-formal-kernel.md` §10.1 (finding classes),
>   §10.4 (proof boundary), §10.6 (R), §10.7 (B0 accepted, A14 gate).
> - Entry state: B0 PASS, `docs/notes/p037-phase-b-proof-boundary.md` and
>   `formal/p037-kernel/proof-boundary.json`.
> - Base: `0e2c01a`, the head of #372. Branch:
>   `research/p037-phase-b1-shadow`.
>
> Evidence tags as elsewhere: `REPOSITORY FACT`, `MEASURED OBSERVATION`,
> `INFERENCE`, `OWNER RULING`.

## 0. Fixed by the owner (OWNER RULING, 2026-09-28, recorded verbatim in meaning)

These are the frame of the contract, not choices it makes.

1. B1 is shadow-only. It changes no MOS, verdict or diagnostic, no
   `ConsumesParam`, and no `own-bridge` behavior.
2. `own-bridge` is untouched in B1.
3. The home is a new crate, `own-guarded`.
   - It is the only Rust crate allowed to depend on `p037-kernel`.
   - An executable architecture guard enforces this, because
     `own-diagnostics/tests/dag.rs` sees only workspace-internal edges.
4. `own-shadow` may depend on `own-guarded` to produce guarded-vs-legacy
   reports.
5. `own-bridge → own-guarded` is **not** pre-authorized; that edge is phase C.
6. All 16 B0 entry obligations are B1 acceptance conditions.
7. A14 remains conditional static-dispatch debt. B1 may **measure** it; B1 may
   not solve it or assume it away.
8. The first shadow population collects the A14 exposure metrics and the R
   record-absence metrics that the later kill-gates need.
9. These all degrade to **`NO_GUARDED_EVIDENCE`**, never to a positive
   conclusion:
   - an ambiguous body⋈sidecar join;
   - a missing record or sidecar;
   - an unresolved positive fact;
   - a solver bound failure;
   - unsupported placement.

## A. Question

Can a guarded summary be computed for the real fact surface in shadow, with
the existing kernel reused rather than re-implemented and every B0 obligation
discharged by an executable control? That is, reading only A2's sidecar, the
legacy body and the `functions[]` records. Two things must also hold:

- every place where the facts do not support a guarded conclusion yields
  `NO_GUARDED_EVIDENCE` rather than a guess;
- every difference against the legacy summary is either one of the three
  declared P-037 classes or explicitly degraded.

If not, **STOP** before phase C. The finding is classified under §10.1, and
case 5 goes back to the owner.

## B. Necessary conditions (all must hold for PASS)

**N1 — architecture, executable.**
- `own-guarded` is a workspace member. Its workspace dependencies are
  exactly `own-ir`, and its only non-workspace path dependency is
  `formal/p037-kernel`.
- `own-shadow` gains `own-guarded`. No other crate gains either.
- A new guard (a `dag.rs` test reading every `Cargo.toml` under `rust/`,
  mirrored by `scripts/p037_proof_boundary.py`) fails when:
  - any crate other than `own-guarded` names `p037-kernel`;
  - any crate other than `own-shadow` names `own-guarded`;
  - `own-bridge` / `own-cli` / any core crate reaches either, directly or
    transitively.
- `own-bridge → own-guarded` is absent and asserted absent.

**N2 — zero semantic cut.** `rust/` is an A2 evidence instrument path
(`scripts/p037_evidence.py`), so adding a crate moves the instrument by
definition. The A2 snapshot differential therefore refuses to compare across
B1, and that refusal is correct. The pre-registered evidence instead:
- **Source-level:** `git diff base..head` touches nothing under `ownlang/`,
  `rust/crates/{own-bridge,own-cli,own-ir,own-lowered,own-analysis,own-cfg,own-syntax,own-diagnostics}/src`,
  `scripts/own-check.sh` or `spec/`. The exceptions are the `dag.rs` guard
  test and `Cargo.toml` / `Cargo.lock` workspace membership. The checker
  enforces the path set.
- **Binary-level:** the release `own-cli` built at the base and at the head
  with the same toolchain has the **same sha256**. If it does not, the
  fallback is a full MOS/verdict before/after take with the instrument move
  declared. If the harness cannot express that, **STOP**: an
  evidence-infrastructure addition (case 4) comes before B1 can pass.
- **Extractor-level** (only if the A14 side report of N6 lands in the
  extractor): with the flag absent, the census is byte-identical on both
  engines, and the facts of the 137-file corpus and the repo tree are
  byte-identical to the base.

**N3 — the 16 B0 obligations, each with an executable control in
`own-guarded`'s tests (or in `own-shadow` for report properties).**

| B0 id | B1 acceptance control |
|---|---|
| WF / EWF | a system or coordinate that fails the ported well-formedness predicates is `NO_GUARDED_EVIDENCE`; it is never solved |
| A2 | Id/Neg only for a resolved callee, at the callee's elected guard ordinal, from `param{source_param}`; an unresolved callee with a param at that position is Opaque |
| A3 | Uncond seeds only via `Cells::diag`; apply(Uncond) lowers the collapse |
| A4 / A15 | seeds and masks only through the fail-closed join. The B0 probe shapes (`docs/evidence/p037-b0-probes`) plus `ctor-initializer` are fixtures, each with the pre-registered outcome from B0 §E.6: placeable, or `NO_GUARDED_EVIDENCE` with its reason |
| A5 | the transform table: `bool_const`/`null_literal`/`object_creation` → ConstPos/ConstNeg (canonical orientation); `param` → Id/Neg under A2; `call_result`/`opaque` → Opaque in the solver |
| A6 | the driver's step composes `p037_kernel::{read, contribute, Cells::join, import}` (checked: `own-guarded` defines none of the kernel's types or algebra) |
| A7 | a full sweep by construction, with no schedule parameter; F8 extended to scan `own-guarded` |
| A8 | application only through `p037_kernel::apply`; F9 scans `own-guarded`; **the K7 witness ported onto the adapter**: a `(must, ⊥)` unselected coordinate built from real facts lowers to plain |
| A9 / A10 / A11 | a missing record, missing sidecar, unresolved callee or ambiguous join reads as Unknown / `NO_GUARDED_EVIDENCE`, never ⊥. `record-absence-boundary` is a required control: a mutant that reads absence positively turns it red |
| A12 | the pass bound is `n·HEIGHT+1` per SCC; exceeding it (fault-injected) is `NO_GUARDED_EVIDENCE` for the SCC, never a partial value or a panic |
| A13 | only `fin()` cells cross an SCC boundary; a two-SCC fixture whose callee has a residual ⊥ cell must not yield `must` at the caller |
| A14 | every report carries `static_dispatch_conditional: true`; nothing in `own-guarded` reads, upgrades or degrades on dispatch |

**N4 — required-read.** The contradictory-sidecar fixture of A2 flips role
(§10.3):
- in B1 it must **change** the guarded shadow result, which proves the
  sidecar is actually read;
- it must still leave MOS and verdicts unchanged (the inertness script, with a
  guarded layer added).

**N5 — every guarded-vs-legacy difference is classified, at two separate
levels.** Legacy is `own-bridge`'s MOS, read through `own-shadow`.

- **Legacy comparison is justified by G-T2b and nothing else.** G-T2a is the
  pre-finalization lax refinement of the guarded lfp against the *collapsed
  semantic system* `F_C` (`C(lfp F_G) ≤ lfp F_C`, §7.2). It says nothing
  about legacy, which A0.5 established by splitting G-T2.
- G-T2a may be checked as a separate **internal algebraic invariant** of the
  shadow run (guarded collapse against the collapsed system, before
  finalization). A violation of it is an implementation defect, never a
  classification.

**Summary report**, one row per coordinate, each in exactly one class:
- `EQUAL`: the finalized guarded collapse equals the legacy value;
- `SUMMARY_REFINEMENT`: the finalized guarded collapse is strictly below the
  legacy value (G-T2b, first disjunct);
- `LEGACY_HONESTY`: guarded `unknown` against legacy `may` (G-T2b class 3);
- `NO_GUARDED_EVIDENCE(reason)`;
- `UNEXPLAINED`: anything else.

**Application report**, one row per relevant call site, each in exactly one
class:
- `EQUAL`: the guarded lowering, through `apply` with the site's selection,
  equals the legacy lowering;
- `APPLICATION_REFINEMENT`: the selection at the site gives a different
  lowered effect than lowering the collapse, and that effect is within what
  G-A1/G-A2 permit;
- `NO_GUARDED_EVIDENCE(reason)`;
- `UNEXPLAINED`.

`UNEXPLAINED > 0` in **either** report is a KILL (§D).

**N6 — the first shadow population collects the gate metrics.**
- **A14 exposure** (measurement only; OwnIR is not amended, per §10.7):
  - relevant calls, total;
  - exact calls (static, non-virtual, or a sealed/struct target);
  - virtual / abstract / interface / override dispatch candidates;
  - candidates in a guarded summary chain;
  - candidates whose **observed first-party targets in this compilation**
    have different guarded summary classes. The class is computed by the
    shadow measurement, never by the side report;
  - the subset where the static target yields MUST and some observed target
    does not: the A14 hard-KILL witness count.

  Dispatch class is not in the facts. The measurement therefore comes from a
  **side report** of the extractor. It is strictly measurement:
  - it is opt-in, and writes a separate JSON keyed by call site;
  - it is not OwnIR and not read by either engine, and facts are
    byte-identical when it is off (N2);
  - it emits only Roslyn/source dispatch metadata: `dispatch: exact | open`,
    plus the **observed first-party targets in this compilation**;
  - it never calls those targets "admissible" or "the implementations". For
    an open-world virtual/interface call they are not the exhaustive runtime
    set, and the report says so;
  - it computes no guarded summary class and decides nothing about safety;
    that is the shadow measurement's job;
  - no conflicting observed target never turns an `open` call into one proven
    safe for phase C. `open` stays `open` in every count.
- **R record-absence:** first-party resolved callees with no `functions[]`
  record, how many guarded paths end there, and the share of otherwise-eligible
  guarded chains that break on R.
- **Degradation census:** `NO_GUARDED_EVIDENCE` counts by reason (join
  ambiguity per rule clause, missing record, missing sidecar, unresolved,
  bound, malformed, expression form, no body op).

## C. Cheap falsifiers (each demonstrated to fire before the result)

| id | mutation | must happen |
|---|---|---|
| G1 | `own-bridge` (or `own-cli`, `own-ir`) gains `own-guarded` or `p037-kernel` | the architecture guard fails |
| G2 | a second crate gains `p037-kernel` | the architecture guard fails |
| G3 | `own-guarded` defines its own `join` / `Transfer` / `apply`-like lowering | the reuse guard fails (A6/A8) |
| G4 | the driver takes a schedule, or `own-guarded` calls `solve_with` / `elect_with` / `lfp_chaotic` | F8 fails |
| G5 | `own-guarded` lowers/collapses outside `apply` | F9 fails |
| G6 | the join resolves an ambiguous line (e.g. `Probe.TwoIfs`, `c && F(s)`) to a placement instead of `NO_GUARDED_EVIDENCE` | the A15 fixture test fails |
| G7 | absence (R, missing sidecar) or an unresolved callee read as ⊥ / no / must | the A9–A11 tests fail, and `record-absence-boundary` goes red |
| G8 | the ported K7 witness mutated so that application skips `fin` | the adapter-level K7 test fails |
| G9 | a raw cell exported across an SCC | the A13 two-SCC test fails |
| G10 | the contradictory sidecar no longer changes the shadow | the N4 required-read test fails |
| G11 | the report drops `static_dispatch_conditional` or acts on dispatch | the A14 report test fails |
| G12 | an own-bridge / own-cli source change sneaks in | the N2 path guard fails |
| G13 | a synthetic guarded-vs-legacy pair outside the classes of its level | the summary or application classifier reports `UNEXPLAINED` (it is not silently bucketed); a pair whose only justification would be G-T2a is `UNEXPLAINED` too |
| G14 | a shadow run over any input not at `population_commit` `571669e` | the report generator refuses; population drift is not a measurement |
| G15 | the side report marks an `open` call as safe, or emits a summary class | the side-report schema test fails |

## D. Hard KILL / PASS

**KILL** gives `RESULT: FAIL — B1 BLOCKED`, lists the blockers, fixes no
semantics here, and triggers when:

1. any MOS, verdict or diagnostic moves (N2 fails);
2. the architecture guard can be satisfied only by an edge the owner did not
   authorize;
3. any obligation of N3 has no executable control, or its control is only a
   comment;
4. any positive guarded conclusion (a selected MUST / NO, or borrow) is
   produced where §0.9 requires `NO_GUARDED_EVIDENCE`;
5. `UNEXPLAINED > 0` in the summary or the application report. Each such
   difference is classified under §10.1 before anything else happens; case 5
   goes to the owner;
6. the fail-closed join (A15) cannot be implemented from the A2 facts without
   a sidecar/OwnIR change. That is a case-5 STOP, as B0 §E.3 item 3 foresaw;
7. A14 is assumed away or acted on;
8. the kernel is re-implemented rather than reused;
9. any hard cap in §F is reached with the work unfinished. That is a STOP
   and review: no 2x grace and no quiet overrun.

**PASS** gives `RESULT: PASS — GUARDED SHADOW READ ESTABLISHED`, and requires
all of:
- N1–N6 hold;
- G1–G15 fire;
- the first shadow report is committed as evidence (population, commit,
  toolchain), together with the A14 and R metrics;
- the degradation census, and the classification counts of both reports with
  `UNEXPLAINED = 0`.

A PASS authorizes nothing further by itself. The A14 gate and the R value
gate are separate steps that consume this report. Phase C
(`own-bridge → own-guarded`, authoritative guarded summaries) needs its own
authorization.

## E. Population (the first shadow run)

**`population_commit` = `571669e`** (frozen by the owner). Every input is
read from that exact commit, materialized from git as the A2 evidence harness
does, and the run uses one toolchain.
- The legacy side is `own-bridge`'s MOS, the Rust production core. Python/Rust
  parity is already gated by P-022, and B1 does not re-measure it.
- Fixtures B1 adds later are **acceptance tests only**; they are never added
  to this measurement population (G14).

The population:
- the repository C# tree (`frontend/`, `audit/`);
- the committed corpus (the 137 files of `corpus/real-world`, `wpf`, `di`,
  `fixtures`, `p036-bakeoff`);
- `corpus/p037-shapes` (23 shapes);
- the P-037 controls `corpus/p036-bakeoff/{guarded-consume-*, gv4-control-*,
  legacy-honesty-*}`;
- the B0 probes `docs/evidence/p037-b0-probes`.

The report's own schema is versioned (`p037-guarded-shadow/1`). It is
evidence, not a gate on verdicts.

## F. Budget and stop point

Hard caps (owner amendment; measured as handwritten lines, excluding blank
lines and comments, by the same counter for every file):

| scope | cap |
|---|---|
| `own-guarded`, non-test Rust | **900** |
| `own-shadow`, B1 additions (the report entry point) | **200** |
| extractor A14 side report, C# | **150** |
| **everything B1 hand-writes**: code, tests, guards, fixtures' harness code and scripts | **2500** |

- The report entry point follows owner decision R-1: stdin is the facts
  document, stdout is the report, and it takes no path arguments.
- No new framework.
- **Reaching any cap with the work unfinished means STOP and review.** There is
  no 2x grace; the #369 overrun is the precedent this rule exists for.

Stop point: the PASS/FAIL result, the committed first shadow report, and the
metrics for the A14 and R gates. **No phase-C wiring, no A14 solution, no R
experiment, no #368 fix.**

Implementation starts only after the owner has reviewed this contract.

## G. Owner amendments (review of `571669e`, recorded 2026-09-28)

The owner reviewed the pre-registration at `571669e` and required four
corrections before any implementation. They are applied above.

1. **N5.** G-T2a is only the pre-finalization refinement against `F_C` and is
   never a justification for a legacy comparison. Legacy classification rests
   on G-T2b, and summary-level and application-level classification are
   separate reports.
2. **Population.** Every first-shadow population input is frozen at exact
   commit `571669e`. Later B1 fixtures are tests, never additions to that
   measurement population.
3. **Budget.** Hard caps replace the approximate and 2x budgets:
   `own-guarded` 900 non-test Rust, `own-shadow` 200, A14 C# 150, total
   handwritten code/tests/guards 2500. Reaching any cap unfinished means
   STOP.
4. **A14 side report.** It is strictly measurement: `exact | open` plus the
   observed first-party targets. It never claims those targets exhaust runtime
   dispatch and never computes semantic conclusions.

Also accepted as written:
- The zero-semantic-cut evidence of N2. An identical `own-cli` SHA is the
  cheap fast path, not a theorem. A different SHA is not a KILL by itself: it
  runs the recorded fallback (before/after MOS and verdicts on the frozen
  population), and if the tooling cannot honestly express the instrument
  move, the tooling is fixed first.
- The architecture of §0.

Implementation is authorized from the commit that records these amendments.
The draft PR is opened before any Rust code, so this SHA is visible and the
boundaries do not move after it.
