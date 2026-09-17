# formal/p037-kernel — the P-037 guarded-transfer kernel, checked

The A0 spike of the SHRINK hand-off (`docs/notes/p036-bakeoff.md` §8.5):
the pure algebra of [P-037](../../docs/proposals/P-037-guarded-effect-summaries.md)
as one small Rust crate, with every property written twice over the **same**
functions — a [Kani](https://model-checking.github.io/kani/) proof harness
(symbolic inputs, bounded model checking) and a plain `cargo test` twin
(exhaustive where the domain allows, seeded-random otherwise). The research
note is `docs/notes/p037-formal-kernel.md`.

What it is **not**: an implementation of P-037 in the analyzer (P-037 §10
keeps that post-cutover), a member of the `rust/` core workspace (the crate
graph there is the architecture, P-022), or anything wired to a verdict.
When A1 lands, these functions move into the post-cutover summary engine
unchanged; nobody writes "the production version" of them.

## Layout

```text
src/lib.rs                    the kernel (~700 lines with docs):
                              Transfer (INF-L1/L2), Cells (G-L2), Election +
                              import (G-S1), Transform/Mask (G-S5/G-F2/G-S4),
                              System::step (F_G), ::collapsed (F_0 of §7.2),
                              ::today (ownir.py's derivation ladder), the
                              bounded Jacobi/chaotic solver (G-F1), apply
                              (G-A1/G-A2), the residual-⊥ lemma models (§7.3)
src/properties/mod.rs         enumerators, a seeded PRNG, lfp helpers
src/properties/lattice.rs     K1 K2 K5
src/properties/election.rs    K4, K10 (election half), §8 row 11
src/properties/transforms.rs  K3 K8 K12
src/properties/solver.rs      K10 (fixpoint, least, schedule-independent)
src/properties/application.rs K6 K7 (+ the unfinalized-read witness), K13 rows
src/properties/refinement.rs  K9, K11 (collapsed system; today's derivation)
```

## Trusted-input boundary

```text
TRUSTED (not modelled):  guard eligibility (G-V4), cell-local definite-release
                         facts (G-S2/G-S3), which forward sits under which
                         literal (G-S4), the Roslyn/CFG derivation of all of it
VERIFIED FROM HERE:      election join + import, cells join, the five edge
                         transforms + mask, the SCC solver, collapse, fin,
                         application, and the lax-refinement arguments of G-T2
```

The kernel proves: **if the frontend hands over honest primitive facts, the
summary kernel cannot turn them into a fabricated `must`** (K6/K7), and the
solver is a schedule-independent least fixpoint (K10).

## Run

```text
cargo test                      # the exhaustive / randomized twins (~20 s)
cargo clippy --all-targets      # the rust/ workspace's strict lints, copied
cargo kani                      # every #[kani::proof] harness (needs cargo-kani;
                                #  22 harnesses, ~14 min sequential on 4 cores)
cargo kani --harness k9_residual_bottom_lemma_all_three_groundings
```

`cargo kani setup` installs the pinned toolchain and CBMC once.
