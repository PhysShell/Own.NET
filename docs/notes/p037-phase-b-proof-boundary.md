# P-037 Phase B0: the formal/production proof-boundary audit (pre-registered)

> Status: **RESULT: PASS — PROOF BOUNDARY CLOSED FOR PHASE B SHADOW (§E),
> with 16 B1 entry obligations and 2 phase-C obligations. One phase-C item
> (A14, static dispatch) needs an owner decision before phase C.**
> §§A–D were pre-registered in `ee73dd1`, before any audit artifact, and are
> left as registered; the result is judged against them rather than an
> impression afterwards. Governance:
> `docs/notes/p037-formal-kernel.md` §10.1 (finding classes), §10.4 (the
> Phase-B proof boundary), §10.6 (the R ruling). Base: A2.2 closed on #371 at
> `0ae821356ae03cd185e845cc46be45b700f1e064`. Branch:
> `research/p037-phase-b-proof-boundary`.
>
> Evidence tags as elsewhere: `REPOSITORY FACT`, `MEASURED OBSERVATION`,
> `INFERENCE`, `OWNER RULING`.

This change **starts no semantic wiring**. It does not touch guarded summary
values, solver output, MOS, verdicts, `ConsumesParam`, Roslyn sidecar facts,
the OwnIR schema, or kernel semantics.

## A. Question

Can every load-bearing formal assumption of P-037 be honestly linked to one of
two things?

- a **production guarantor** that exists today, with a concrete mechanism and
  an executable control;
- an explicit **outside-the-Kani-boundary** declaration, stating what is not
  proved, why, and what controls it.

And can this be done without finding a hidden precondition between the Roslyn
facts and the guarded kernel?

If not: **STOP** before any semantic implementation.

### A.1 What was already seen before registration (disclosed, not hindsight)

Reading the governing text and the kernel, and running two extractor probes
(scratch `.cs` files, not committed), established the following before these
criteria were written. They are listed so they are judged by the rule below,
not argued afterwards.

- `REPOSITORY FACT`: nothing in production (`rust/`, `ownlang/`) references
  the kernel crate `formal/p037-kernel`. The A1 production landing has not
  happened. The only production code on the P-037 path today is the fact
  producer (Roslyn `BuildGuardedFacts`) and the OwnIR doors, which validate the
  sidecar and keep it inert.
- `REPOSITORY FACT`: the kernel is bounded (`MAX_COORDS = 3`,
  `MAX_EDGES = 2`), and its `System` holds one SCC. It models neither
  composition across SCCs nor a dynamic driver.
- `REPOSITORY FACT`: `solve` / `elect` are Jacobi, so they visit every live
  coordinate on every pass by construction. `solve_with` / `elect_with` take an
  arbitrary schedule, which is the #368 hazard.
- `MEASURED OBSERVATION` (probe): the kernel's G-S4 mask ("which forward sits
  under which literal") has no field in the sidecar.
  - A hypothesis was tested and **refuted**: that two programs differing only in
    whether a borrowing forward sits inside or after an eligible `if` produce
    byte-identical facts. They don't. Legacy lowering emits a `use` op placed in
    the body tree, and the sidecar call carries its `statement_line`.
  - Placement is therefore recoverable only by *joining* the sidecar to the
    legacy body by line (the §10.5 call-site identity). Body `if` ops carry no
    column, so two `if`s on one line make the guard↔`if` join ambiguous
    (observed).
- `REPOSITORY FACT`: the legacy `ConsumesParam` and the whole-analyzer summary
  keying read the *statically resolved* callee's body. Virtual or override
  dispatch is not represented anywhere in the facts.

## B. Necessary conditions (all must hold)

- **N1 — harness inventory complete.**
  - The set of `#[kani::proof]` functions under `formal/p037-kernel/src` is
    derived from source, never from a maintained number.
  - The fast set (`ci.yml` job `formal-p037`) and the heavy set
    (`formal-p037-gate.yml`) are also derived from source.
  - It must hold that `fast ∩ heavy = ∅` and `fast ∪ heavy = source`, with
    `missing = extra = overlap = 0`.
  - A harness in no set, or a CI name that is no harness, is a FAIL.
- **N2 — every harness has a human claim.** Each records:
  - the harness;
  - its P-037 claim;
  - a concrete production subject: kernel symbols such as `Transfer::join`,
    `System::step`, `solve`, `apply`, never "kernel correctness";
  - its assumptions;
  - its CI class.
- **N3 — every load-bearing assumption is classified exactly once**, as
  `PRODUCTION_GUARANTOR` or `OUTSIDE_KANI_BOUNDARY`.
  - A `PRODUCTION_GUARANTOR` needs a mechanism that exists today. It must say
    what it guarantees, where, up to which consumer, and what happens on
    violation. It also needs an executable control.
  - An `OUTSIDE_KANI_BOUNDARY` entry states what is not proved, why that is
    deliberate, and what controls it. "Nothing yet, because nothing consumes
    it" is allowed only when a named obligation binds the first consumer (B1).
  - An assumption that holds only on a comment fails.
  - "assumed", "obvious", "frontend handles this" and "well_formed somehow"
    are rejected.
- **N4 — the bounded adapter is stated honestly.**
  - Kani `MAX_COORDS = 3`, `MAX_EDGES = 2`, checked against `lib.rs`.
  - Production is a dynamic coordinate/edge count.
  - No claim that Kani proved a production-size bound. The generic Rocq result
    (#369/#370) may be cited as external research evidence only, never as a
    dependency.
- **N5 — production well-formedness has guarantors.** Election shape and
  import, `Uncond` diagonality, `id`/`neg` admissibility, guard stability
  (G-V4), cell-local release consistency, finalization before application,
  fair/full visitation, and missing record/sidecar under R. Each must have one
  of:
  - a producer invariant;
  - runtime/kernel validation;
  - construction-by-API;
  - an executable negative control;
  - `OUTSIDE_KANI_BOUNDARY`.
- **N6 — application ordering is pinned.** F2 (`fin` before
  select/collapse/apply) has a control that breaks if raw solver state is
  applied before finalization, and a mutant proves it breaks. A Kani harness
  alone does not count.
- **N7 — fairness / #368 is not hidden.** The production-side contract is one
  of three:
  - (A) full visitation by construction;
  - (B) validated coverage;
  - (C) #368 as a mandatory blocker before any schedule-taking API is used.

  "The caller is expected to pass a fair schedule" is a FAIL. So is any
  production path that could call the solver with an unchecked, externally
  supplied schedule.
- **N8 — R stays fail-closed.** A missing `functions[]` record and a missing
  `guarded_facts` are both recorded as `NO_GUARDED_EVIDENCE`. They are never
  `no effects`, borrow, unconditional, guard-irrelevant, or `must`.
  `record-absence-boundary` is the Phase-B negative control.

## C. Cheap falsifiers (each must be demonstrated to fire)

| id | mutation | must happen |
|---|---|---|
| F1 | drop one real harness from a CI set; add a fake harness name | audit FAIL (missing / extra) |
| F2 | put one harness in both fast and heavy | audit FAIL (overlap) |
| F3 | a manifest assumption with no class, or a vague guarantor | audit FAIL |
| F4 | a guarantor or control pointing to a path/symbol that does not exist | audit FAIL |
| F5 | the kernel's `apply` stops finalizing (`apply before fin`) | the finalize-before-apply control goes red (`cargo test`, temp copy) |
| F6 | R absence reinterpreted as any positive claim | audit FAIL |
| F7 | a minimal #368-class unfair schedule | an executable witness shows `Some(non-fixpoint)`, and the audit fails if fairness is "the caller's job" |

Additional falsifiers found before registration (§A.1), judged by the same
rule:

| id | mutation | must happen |
|---|---|---|
| F8 | a production file (outside `formal/`) that calls a schedule-taking kernel API (`solve_with`, `elect_with`, `lfp_chaotic`) | audit FAIL: this makes N7 option (C) executable, not prose |
| F9 | a production file that imports the kernel and lowers or collapses cells directly instead of through `apply` | audit FAIL: the N6 bypass |
| F10 | a harness whose body uses an assumption-bearing generator or predicate (`any_system`, `any_schedule`, `release_cells_have_no_edges`, `no_unknown_seed`, …) without listing the matching assumption | audit FAIL: load-bearing assumptions are derived from source, not only declared |

## D. Hard KILL / PASS rule

**KILL**: `RESULT: FAIL — PHASE B BLOCKED`, with the blockers listed and no
semantic code fixed here, if any of these holds:

1. the harness inventory does not match the CI partition;
2. a load-bearing assumption is unclassified;
3. a `PRODUCTION_GUARANTOR` lacks an existing mechanism plus a control;
4. no fairness production contract exists;
5. the finalization ordering is not pinned by an executable control at the
   seam production will use;
6. R absence can be interpreted positively;
7. a bounded Kani result has to be presented as a production-unbounded proof;
8. going green requires changing P-037 semantics;
9. an assumption whose only possible guarantor is the future B1 adapter cannot
   be discharged fail-closed from the A2 fact surface. That is a **hidden
   precondition between the Roslyn facts and the kernel**: STOP. Such an
   amendment is case 5 (§10.1), not case 2.

**PASS**: `RESULT: PASS — PROOF BOUNDARY CLOSED FOR PHASE B SHADOW` only if:

- the inventory is exact and the CI partition exact;
- every assumption is classified and every guarantor concrete;
- negative controls are mapped;
- #368 is explicitly handled;
- R is explicitly fail-closed;
- no semantic wiring was done;
- F1–F10 all fire.

A PASS authorizes the separate step B1 (guarded shadow read, no verdict). It
also carries the list of B1 entry obligations recorded in the manifest. B0
does not implement B1.

Assumptions discovered by this audit are case 2 (a proof-boundary manifest
amendment) when they can be discharged fail-closed. They are case 5 (STOP)
under KILL 9.

**Budget.** One small checker (`scripts/p037_proof_boundary.py`), one manifest
(`formal/p037-kernel/proof-boundary.json`), this note, small selftests and
mutants. A new general verification framework is a STOP.

## E. Result (MEASURED OBSERVATION unless tagged)

```text
PHASE: B0 proof-boundary audit
RESULT: PASS — PROOF BOUNDARY CLOSED FOR PHASE B SHADOW
SEMANTIC WIRING: NONE
HARNESS INVENTORY: 23 source / 15 fast + 8 heavy / 0 missing / 0 extra / 0 overlap
UNCLASSIFIED ASSUMPTIONS: 0   (16 load-bearing: WF, EWF, A1–A12, A13–A16)
#368: C_BLOCKER — no production file may call a schedule-taking kernel API
      (executable rule); #368 stays open, a blocker before any such use
R: FAIL-CLOSED — NO_GUARDED_EVIDENCE, record-absence-boundary pinned
```

The artifacts:
- `formal/p037-kernel/proof-boundary.json`, the manifest;
- `scripts/p037_proof_boundary.py` (`--check`, `--selftest`, `--mutants`);
- `tests/test_p037_proof_boundary.py` (`--check` and `--selftest` on every
  `tests/run_tests.py`);
- a `--mutants` step in the `formal-p037` CI job;
- the #368 witness `issue_368_unfair_schedule_returns_a_non_fixpoint` (a
  kernel test; no kernel code changed);
- the probe evidence under `docs/evidence/p037-b0-probes/`.

### E.1 Necessary conditions

| # | result |
|---|---|
| N1 | holds. All three sets are derived from source: 23 `#[kani::proof]`, 15 in `ci.yml` `formal-p037`, 8 in `formal-p037-gate.yml` `heavy-kani`. Each loop really runs `cargo kani --harness "$h"`. The README's hand-kept "22 harnesses" was stale (k11b arrived in A0.5) and is replaced by a pointer to the derivation |
| N2 | holds. Every harness has a claim, concrete kernel subjects (each checked to be a `fn` in `lib.rs`), its assumptions and its CI class |
| N3 | holds. Every assumption has exactly one class. `PRODUCTION_GUARANTOR` is used only where the mechanism exists **today**: A1, A2, A5, A10 are producer invariants pinned by census shapes; A7 and A8 are production-tree checker rules. Every kernel-only witness is labelled `seam: kernel`, and the checker refuses to relabel one as production |
| N4 | holds. `MAX_COORDS = 3` / `MAX_EDGES = 2` are checked against `lib.rs`. Production is `dynamic`, and `kani_proves_production_bound: false`. The Rocq results are named as external evidence only |
| N5 | holds, as classified. Election shape/import (EWF, A2, A5), Uncond diagonal (A3), id/neg (A2), G-V4 (A1), cell-local release (A4), fin before apply (A8, A13), full visitation (A7) and R (A11) each have a guarantor or an OUTSIDE entry with a B1 obligation |
| N6 | holds. `apply` and `lower` finalize by construction. F5a/F5b (removing either `fin`) are killed by the `k7_` twins (`--mutants`). The production-facing rule F9 fails the audit if a production file that imports the kernel lowers or collapses cells outside `apply` |
| N7 | holds with **option C**. Measured: no production file references the kernel at all, so none calls `solve_with` / `elect_with` / `lfp_chaotic`, and rule F8 makes that executable. The #368 witness shows `Some(non-fixpoint)` for both the solver and the election. The dynamic driver must be a full sweep with no schedule parameter (A7). **#368 stays open** as a defect of the generic API and is a mandatory blocker before that API is used in production |
| N8 | holds. A11 is `NO_GUARDED_EVIDENCE`, with eight forbidden positive readings. `record-absence-boundary` is its control, and F6 (reading absence as `borrow`) fails the audit |

### E.2 Falsifiers

| id | outcome |
|---|---|
| F1 | fires: a dropped harness gives `missing`, a fake name gives `extra`, and a loop that stops running `cargo kani` fails |
| F2 | fires: `overlap` |
| F3 | fires: no class, and a vague guarantor ("the frontend handles this") |
| F4 | fires: a nonexistent guarantor path, and a nonexistent control symbol |
| F5 | fires (`--mutants`): apply-without-fin is killed by `k7_unknown_opaque_and_differing_unselected_cells_never_consume` and `k7_witness_an_unfinalized_opaque_read_would_consume`; lower-without-fin is killed by the first |
| F6 | fires: absence read as `borrow` |
| F7 | fires: fairness "left to the caller" fails, and the #368 witness holds on the real kernel |
| F8 | fires: a kernel-importing production file calling `solve_with`. **A same-named unrelated `solve_with` stays green** (see E.3 item 5) |
| F9 | fires: a kernel-importing production file that runs `lower(c.collapse())` |
| F10 | fires: `k10a` stops declaring `WF` although its body calls `any_system` |

The selftest also covers: A8 with apply ordered before fin; a claimed
production-size bound; a formal-crate witness relabelled as production; and
a recorded blocker, which fails the gate.

### E.3 Findings, classified under §10.1

1. **A13: cross-SCC export must be finalized (case 2).**
   - The kernel models one SCC; composition across SCCs is not modelled.
   - The F2 hazard exists at the SCC boundary too: through an Opaque edge a
     raw `(must, ⊥)` collapses to `must`, while `(must, no)` collapses to
     `may`.
   - The legacy driver already finalizes before export (`mos.rs`,
     `unwrap_or(Transfer::No)`). The guarded driver must do the same; this is
     a B1 obligation.
2. **A14: static dispatch (case 2, inherited; phase-C obligation). This is
   the finding closest to KILL 9.**
   - The kernel reads the summary of the statically resolved callee. The
     sidecar has no dispatch fact, so the assumption cannot be discharged
     fail-closed from the A2 facts.
   - Why it is not a B0 kill:
     1. it is not new to P-037: legacy `ConsumesParam` and the MOS keying make
        the identical assumption in today's verdicts;
     2. B1 moves no verdict;
     3. `INFERENCE`: while `ConsumesParam` folds any-path disposal into a
        release, the guarded consume set through a virtual call stays within
        the legacy end-to-end one.
   - It becomes live once A1 removes that fold. **Owner decision needed before
     phase C**: either a dispatch fact (a case-5 OwnIR amendment), or a ruling
     that accepts the inherited assumption. B1's shadow report must state that
     its refinement counts are conditional on static dispatch.
3. **A15: the G-S4 masks and G-S2/G-S3 seeds come from a body⋈sidecar join
   (case 2).**
   - The pre-registration's candidate hidden precondition was that forward
     placement cannot be recovered from the A2 facts. It was **refuted**:
     legacy lowering puts a `use` / `release` op in the body tree for a
     relevant call, and the sidecar's `statement_line` joins to it.
   - What remains is a join whose ambiguity is detectable in every probed
     case. That gives the fail-closed rule recorded in A15.
   - `INFERENCE`: this is a probe-based argument, not a proof. If B1 cannot
     make the join provably fail-closed, B1 must STOP and ask for a placement
     fact (case 5).
4. **A16: normal-return-only semantics (case 2, inherited).**
   - The legacy body drops catch blocks, so a release inside a catch is
     invisible to legacy and guarded alike.
   - This is P-036 vertical B, not widened by P-037. It is a phase-C
     classification note.
5. **Instrument defect, fixed before the result.**
   - The first `--check` run flagged `rust/crates/own-analysis` for
     `solve_with`. That is the Rust core's own worklist dataflow solver over a
     `Schedule` enum, not the P-037 kernel.
   - The rule matched the name alone. It is now scoped to files that name the
     kernel crate, and the selftest pins that a same-named unrelated function
     stays green.
6. **Doc drift.** `formal/p037-kernel/README.md` said "22 harnesses"; the
   source has 23. The count is now derived, never written.

### E.4 Interpretations applied (for the owner to overrule)

- **"Production guarantor" means a mechanism that exists today.** Production
  does not call the kernel yet. Assumptions whose only guarantor would be the
  future B1 adapter or driver are therefore `OUTSIDE_KANI_BOUNDARY`, each with
  a named `b1_obligation` and `derivable_from_a2_facts: true`. None of them is
  relabelled as a guarantor.
- **KILL 5 ("pinned at the seam production will use").** That seam is the
  kernel's `apply` / `lower`: A1 moves the kernel functions rather than
  rewriting them (§8.1, acceptance item 6). It is pinned by F5 and by the
  production-tree rule F9. No guarded production seam exists yet; porting the
  K7 witness to it is a B1 obligation (A8).

### E.5 B1 entry obligations (the manifest is normative; one line each)

| id | obligation |
|---|---|
| WF / EWF | enforce the well-formedness predicates at construction; violation → `NO_GUARDED_EVIDENCE` |
| A2 / A5 | the binding and transform table (Id/Neg only for a resolved callee at the elected ordinal; `call_result` Opaque in the solver) |
| A3 | Uncond seeds only via `Cells::diag` |
| A4 / A15 | seeds and masks only through the fail-closed join; the B0 probe shapes become B1 controls |
| A6 | the dynamic driver composes the kernel's own `read` / `contribute` / `join` / `import` |
| A7 | full sweep, no schedule parameter |
| A8 | application only through `apply`; the K7 witness ported to the B1 seam |
| A9 / A10 / A11 | absence, unresolved callees and ambiguous joins are `Unknown` / `NO_GUARDED_EVIDENCE`, never ⊥ and never positive |
| A12 | pass bound `n·HEIGHT+1`; exceeding it → `NO_GUARDED_EVIDENCE` |
| A13 | export only finalized cells across SCCs |
| A14 | the shadow report is conditional on static dispatch |

### E.6 B0 probe shapes (the A15 join, measured)

Sources: `docs/evidence/p037-b0-probes/Probe{,2,3}.cs`. The extractor output
(bodies and sidecars only) is in `observed.json`, taken at base `0ae8213`
with `--flow-locals`.

| probe | shape | observed | under the A15 rule |
|---|---|---|---|
| `Probe.Branchy` | statement forwards in then / else of a guard | `release@20` in then, `release@24` in else; one call per line | placeable |
| `Probe.TwoIfs` | two eligible `if`s on one line | two `if@31` ops, no column; guards at columns 9 and 36 | guard↔`if` ambiguous → `NO_GUARDED_EVIDENCE` |
| `Probe.Early` | `if (keep) return; Sink(s);` | `if@37 then:[return]`, `release@38` after | placeable (negative literal) |
| `Probe2.InBranch` / `AfterIf` | a borrowing forward inside vs after a guarded `if` | `use@19` inside then vs `use@27` after the `if`; the facts differ | placeable: the indistinguishability hypothesis is **refuted** |
| `Probe2.Behind` | a wrapper forward under an ineligible `if (ready)` | `if@33 then:[release@35]`, `guards: []` | placeable; the kept path must join `no` |
| `Probe3.ShortCircuit` | `c && Ok(s)`, where `Ok` disposes | form `expression`; `if@17` with **empty** branches, so the consuming call has no body op | expression form → `NO_GUARDED_EVIDENCE` |
| `Probe3.Ternary` | `c ? Use(s) : 0` | **no `functions[]` record** | R: `NO_GUARDED_EVIDENCE` |
| `Probe3.Switch` | `case 1: Sink(s);` | lowered to `if@22 then:[release@24]` | placeable |
| `Probe3.TryCatch` | `Sink(s)` inside a catch | form `statement`, but **no body op**; the body models only the try | no op → `NO_GUARDED_EVIDENCE`; a local release in a catch is invisible (A16) |
| `Probe3.Loop` | a one-line `for` | `while@37` and `release@37` on one line | structural op on the line → `NO_GUARDED_EVIDENCE` (conservative) |
| census `ctor-initializer` | `: base(s, keep)` | no body op for the initializer | no op → `NO_GUARDED_EVIDENCE` |

### E.7 What B0 did not do

- No semantic wiring. No change to guarded values, solver output, MOS,
  verdicts, `ConsumesParam`, Roslyn facts, the OwnIR schema or kernel
  semantics; the only kernel change is one new `#[test]`.
- #368 not fixed.
- No R value experiment. That measurement starts after the first real
  Phase-B shadow run (§10.6).
- B1 not started.
