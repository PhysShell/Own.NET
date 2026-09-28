# P-037 Rocq proof package: consolidation of #367 / #369 / #370

This consolidation is not a P-037 reopen event and does not authorize
B2.1a, B2.1b/c, B1 reconciliation, Phase C, or #368 implementation work.
The owner freeze in issue #304 ("P-037 STATUS: IMPLEMENTATION FROZEN")
remains fully in force; this is a research-only consolidation under that
existing freeze.

## Source research

- **#367** (`4b8e2c632d3c5a8a2d1f1597e6c996ae58767fba`) — MathComp spike.
  RESULT: GO (bounded). Established the exporter (links `formal/p037-kernel`
  by path, prints finite-domain truth tables and 300 seeded solver traces),
  the certificate-checker concept, 11/11 mutants killed (including 4 in the
  Rust kernel), and the discovery of the unfair-schedule defect now tracked
  as #368.
- **#369** (`1bfd5ed16c5c6f1ffa257b4091770d1dedd7778c`) — plain-Rocq control.
  RESULT: KILL MATHCOMP, KEEP plain Rocq. Same theorem strength as #367, no
  axioms, same 11/11 mutants, +7.7% LOC over the MathComp version, +1 opam
  package beyond the shared OCaml base instead of +32.
- **#370** (`4ce952102ef4760062bb756731f8d7a3a05a2ec0`) — Election reuse gate.
  RESULT: KEEP generic theory. `Lfp.v` reused with 0 LOC changes; the
  Election instance is 111/180 LOC; 4/4 mutants killed; no axioms.
- **#368** (issue) — `solve_with(sys, unfair_schedule)` can return
  `Some(non-fixpoint)`. Preserved here as a recorded negative result, per
  below. Not fixed by this consolidation; the owner freeze explicitly
  excludes working #368 while implementation is frozen.

## Decision

- KILL MathComp (already decided by #369; this consolidation makes it
  permanent by never depending on `formal/mathcomp-spike/` at all).
- KEEP plain Rocq (Corelib + Stdlib only; Rocq 9.2.0, rocq-stdlib 9.2.0,
  installed and verified via `opam repo add rocq-released
  https://rocq-prover.org/opam/released`).
- KEEP the generic `Lfp.v` theory, unchanged.
- KEEP Election as a separate instance of that same generic theory.
- KEEP the Rust correspondence seam (`Correspondence.v`), regenerated from
  the current `formal/p037-kernel` by the moved exporter.
- Production migration remains FROZEN. Nothing under `rust/`, `frontend/`,
  or `ownlang/` is touched by this commit.

## What this package proves

- **K10 (Jacobi), unbounded**: for any finite coordinate type and any
  join-semilattice with bottom and a strict, bounded rank, Kleene/Jacobi
  iteration from bottom reaches the least fixpoint within `|I| * height`
  steps, and the Rust `lfp_jacobi` loop's `|I| * height + 1` pass budget
  returns exactly it (`jacobi_is_lfp`, instantiated as `k10_jacobi` for the
  P-037 transfer/cells lattice and `k10e_jacobi` for Election).
- **K10c (chaotic/Gauss-Seidel), unbounded**: every FAIR schedule reaches
  the same least fixpoint within the same pass budget (`chaotic_is_lfp`,
  `k10_chaotic`, `k10e_chaotic`).
- **G-T2a, one step and at the lfp**: a one-step lax simulation between the
  guarded-value solver and its collapse lifts to `C(lfp F_G) <= C(lfp F_C)`
  (`lax_simulation_lfp`, `gt2a_one_step`, `gt2a_lfp`).
- **The Rust<->Rocq correspondence seam** (transfer/cells solver only):
  every finite operation (`join`, `fin`, `lower`, `collapse`,
  `contribute(read(...))`, `apply`) is checked equal to the Rust kernel's
  own output on its WHOLE domain, not sampled (`tables_match_rust`); the
  height/pass-bound constants agree (`constants_match_rust`); and for 300
  seeded random SCCs, the Rust kernel's own Jacobi chain and its
  collapsed-system chain are accepted by a proved certificate checker
  (`chain_lfp`), so the Rust answers ARE the Rocq model's least fixpoints
  (`rust_answers_are_rocq_lfps`) — not merely "the Rocq model has a least
  fixpoint too."
- **Non-vacuity of fairness**: an unfair (empty) schedule returns bottom
  after one quiet pass, which is not the least fixpoint once any seed is
  non-bottom (`unfair_schedule_returns_bot`, `k10e_unfair_returns_bot`) —
  the same defect class as #368, recorded as a lemma, not patched.
- **11/11 + 4/4 mutants killed**, `mutants/run_mutants.py` and
  `mutants/run_election_mutants.py`, including 4 kernel-side mutants (D1-D4)
  that only `Correspondence.v`'s seam catches — a mutation that keeps every
  pure-Rocq theorem provable but breaks the Rust kernel still fails this
  package, because the seam regenerates `RustTables.v` from the (mutated)
  kernel and re-checks it. This is the load-bearing distinction between a
  generic-theory mutant, a P037-model mutant, and a Rust-seam mutant that
  section 12 of the consolidation task required be kept.
- All headline results are axiom-free: `Audit.v` (10 results) and
  `ElectionAudit.v` (6 results) each print "Closed under the global
  context" for every listed theorem.

## What it explicitly does NOT prove

- **No Election Rust<->Rocq refinement seam.** `Election.v` is a Rocq
  formalization of the transcribed Election semantics
  (`formal/p037-kernel`'s `Election`/`import`/`ElectionSystem::step`), and
  its generic-theory reuse is real, but there is no exporter/correspondence
  seam tying it to the Rust kernel's own Election output the way
  `Correspondence.v` does for the transfer/cells solver. This was not
  claimed in #370 and is not upgraded here. The actual Rust Election code
  is still checked by Kani (bounded), separately.
- **No G-T2b in Rocq.** G-T2a (`C(lfp F_G) <= C(lfp F_C)`, a formal
  algebraic obligation about the guarded-value/collapse relationship) is a
  Rocq theorem. G-T2b (legacy observational compatibility with the actual
  production analyzer) is a Phase-B empirical claim, never a Rocq theorem,
  and is owned entirely by Phase-B's evidence machinery
  (`docs/evidence/p037-b-epoch.json`), not by this package.
- **No second executable solver.** The only executable Rust semantics this
  package derives correspondence evidence from is `formal/p037-kernel`,
  linked by path from `export/`. Rocq's `step`/`collapsed`/`jacobi`/
  `chaotic` are mathematical functions used for theorem statements and the
  certificate checker, never a second runtime implementation.

## Future reopen requirements

`P037_REOPEN_SOLVER_REQUIREMENT`: a production solver MUST NOT return a
successful stabilized result from a caller-controlled schedule unless
fairness/coverage is enforced.

- Preferred future design: derive the full/fair sweep internally.
- Acceptable future design: validate schedule coverage and fail closed.
- Forbidden future design: fairness exists only as an undocumented caller
  precondition.

This is a future constraint, not a current production patch. `formal/
p037-kernel` is unmodified by this consolidation and #368 is not worked.

If P-037 ever reopens and Election becomes production-relevant, a Rust<->
Rocq correspondence seam for Election must be added before any
theorem-bearing Election claim is used as production justification — the
same seam `Correspondence.v` already provides for the transfer/cells
solver, generalized to the Election instance.

## Mechanical provenance

- `export/` is `formal/mathcomp-spike/export/`'s `Cargo.toml`/`main.rs`
  (PR #367, commit `4b8e2c632d3c5a8a2d1f1597e6c996ae58767fba`) moved
  mechanically. The only change is to the two literal output-string
  constants in `main.rs` (`From mathcomp Require Import boot.` -> `From
  Stdlib Require Import List.`; `From P037Spike Require Import P037.` ->
  `From PlainSpike Require Import P037.`), so the generated
  `theories/RustTables.v` needs no post-process `sed` step. Zero
  computational/semantic change; verified by running the exporter
  unmodified-but-for-those-two-strings against the current
  `formal/p037-kernel` and confirming it builds, runs, and produces the
  exact constants `Correspondence.v` already hard-codes
  (`rust_cells_height = 6`, `rust_transfer_height = 3`,
  `rust_max_passes_cells = 19`).
- `theories/Lfp.v`, `theories/P037.v`, `theories/Audit.v` are byte-for-byte
  identical to `formal/plain-rocq-control/theories/{Lfp,P037,Audit}.v` at
  #369's head (`1bfd5ed16c5c6f1ffa257b4091770d1dedd7778c`).
- `theories/Election.v`, `theories/ElectionAudit.v` are byte-for-byte
  identical to `formal/plain-rocq-control/theories/{Election,
  ElectionAudit}.v` at #370's head
  (`4ce952102ef4760062bb756731f8d7a3a05a2ec0`).
- `theories/Correspondence.v` differs from #369's head by exactly a 2-line
  header comment update describing the new file location (no code, no
  theorem, no proof term changed): "the UNCHANGED exporter of
  formal/mathcomp-spike/export/" -> "export/, moved mechanically from
  formal/mathcomp-spike/export/, PR #367".
- `mutants/run_election_mutants.py` and `loc.py` are unmodified mechanical
  copies (directory-parameterized already; no hardcoded old path).
- `mutants/run_mutants.py` and `election_loc_gate.py` needed small, mechanical
  path-only adjustments caused directly by the `plain-rocq-control` ->
  `p037-rocq` rename and by cutting the `mathcomp-spike/export` dependency
  (renamed `SPIKE` -> `PKG`, dropped the now-unnecessary `sed`
  rewrite step and the `mathcomp-spike/export` copytree call, retargeted
  the `--manifest-path` and the historical-base path lookup). No mutation
  site, mutant, theorem, or LOC limit was altered.
- `check.sh` was rewritten (not mechanically copied) per the consolidation
  task's explicit requirement: it now regenerates `RustTables.v` to a temp
  file and FAILS with an explicit message if it differs from the committed
  one, instead of silently overwriting and reporting green. Verified: a
  deliberately corrupted `theories/RustTables.v` makes `check.sh` exit
  non-zero with the stale-table message and leaves the file untouched;
  regenerating it correctly then makes `check.sh` pass end to end.

## Verification performed

- `./check.sh`: PASS. All of `Lfp.v`, `P037.v`, `RustTables.v`,
  `Correspondence.v`, `Election.v` compile; `Audit.v` (10 results) and
  `ElectionAudit.v` (6 results) each print "Closed under the global
  context" for every result, zero axioms.
- `python3 mutants/run_mutants.py`: 11/11 KILLED (R1-R7 Rocq-side, D1-D4
  Rust-kernel-side; the D-mutants are caught only via `Correspondence.v`).
- `python3 mutants/run_election_mutants.py`: 4/4 KILLED.
- `python3 election_loc_gate.py`: 111/180 (exactly #370's own reported
  figure; unaffected by the consolidation).
- Semantic diff of `Lfp.v` against #369: 0 theorem/definition changes
  (byte-identical). Same for `P037.v`, `Audit.v` against #369, and
  `Election.v`, `ElectionAudit.v` against #370.
- `git diff bd0e84cc412a351e3998ac41e02e56b0abf04551..HEAD -- rust/
  frontend/ ownlang/`: empty.
- `git diff bd0e84cc412a351e3998ac41e02e56b0abf04551..HEAD --
  formal/p037-kernel/`: empty (byte-identical, not merely
  semantically-unchanged).
- `p037_evidence_b.instrument_identity(cf0f95f3f9af85df46d5506a87de806cf3f00c46)`:
  unchanged before and after
  (`c953acda915859449a69ef2866bd947591d48a6d8c302d8955e356f370788c69`),
  confirmed by direct recomputation, not by argument from non-overlap alone
  (the non-overlap of `formal/`, `docs/notes/` with `INSTRUMENT_PATHS` was
  also checked directly against the live list in
  `scripts/p037_evidence_b.py`).
- `ruff check .`: all checks passed, including the four new/adjusted
  Python files under `formal/p037-rocq/`.
- No root Cargo workspace exists in this repository at all (confirmed:
  no `Cargo.toml` at repo root); `formal/p037-rocq/export/Cargo.toml`
  declares its own `[workspace]`, exactly like `formal/mathcomp-spike/
  export/Cargo.toml` and `formal/p037-kernel/Cargo.toml` already did, so
  nothing is newly joined to anything.

## Toolchain

Rocq 9.2.0, rocq-stdlib 9.2.0, Corelib + Stdlib only, no MathComp,
installed via `opam repo add rocq-released
https://rocq-prover.org/opam/released` (the default `opam.ocaml.org` repo
alone only offers `rocq-stdlib` up to 9.1.0; the dedicated Rocq repo has
9.2.0). Manual research toolchain only: not added to `rust/`'s workspace,
not a root dependency, not wired into CI. A future separate owner decision
may wire it into optional CI; this task does not.
