# P-037 Phase B0: the formal/production proof-boundary audit (pre-registered)

> Status: **PRE-REGISTERED. No manifest, checker, or audit code written.**
> §§A–D are committed before any audit artifact, so the result is judged
> against them rather than an impression afterwards. Governance:
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
