# Plain-Rocq control for the MathComp spike (#367)

> **CONTROL FOR: #367.**
> **RESULT: KILL MATHCOMP.**
> Rocq status: **KEEP** (#367 established it; not the subject of this gate).
>
> Everything from "B. Frozen baseline" through "Decision rule" was committed
> in `edccc78` before any plain-Rocq `.v` existed. Sections A and D–I were
> added after the port.

The only question here:

> If MathComp is removed, does proving the same Own.NET guarantees become
> costly or weak enough that the MathComp dependency pays for itself?

Out of scope, by ruling: the election instance (K10e), new theorem targets,
any P-037 extension, the `solve_with` fairness defect (filed as #368), and
production code.

## A. Result

**RESULT: KILL MATHCOMP. KEEP: Rocq.**

- **Same guarantees.** Every headline theorem of #367 is re-proved on Rocq
  9.2 with Corelib + Stdlib only, for the same unbounded generality: any
  finite coordinate type, any edge count, any fair schedule. Every one is
  "Closed under the global context" (§D).
- **Same seam and same sensitivity.** The Rust exporter is reused
  *byte-for-byte*, with only its two import lines retargeted by `sed`. The
  full tables and all 300 certified Rust traces are accepted. **11/11
  mutants are killed at the same lemmas as on the MathComp side** (§G).
- **Cost.** Handwritten model + proof is **532 lines, against MathComp's
  494: +38 lines, +7.7 %**. The frozen threshold was ≤ +148 (+30 %).
- **What MathComp's removal costs** is about 20 more lines of generic
  support: a finite-index record, list sums, a witness lemma, pointwise
  state-equality congruence, product-row equality and Stdlib's `last`. There
  is some `=1` bookkeeping in the chaotic proof. Nothing needs an axiom.
- **What the removal saves**, measured in §H:
  - the whole elpi / Hierarchy Builder / MathComp closure (32 opam packages
    beyond the shared base, against 1 for `rocq-stdlib`);
  - about 190 MB on disk, against 73 MB;
  - the `vm_compute` traps of #367 §E.5;
  - MathComp's package churn.

  The check runs faster too: 5.0 s against 8.7 s.
- **Budget overrun, declared.** 317 new or changed `.v` code lines against
  the 300 limit (+17), mostly mechanical renames: `all` → `forallb`, `==` →
  `*_beq`, `.+1` → `Nat.succ`, `\in` → `In`. The overrun does not affect
  the decision, which is on total size.

## B. Frozen baseline

- The MathComp side is `formal/mathcomp-spike/` at the head of #367,
  `4b8e2c632d3c5a8a2d1f1597e6c996ae58767fba`. This branch,
  `research/plain-rocq-control`, starts from exactly that commit. The
  baseline files are not edited.
- Same counter for both sides: `formal/plain-rocq-control/loc.py` counts
  code lines, meaning non-blank lines outside comments, split into proof
  scripts (`Proof`…`Qed.`) and model (everything else).

| file (MathComp) | model | proof | total |
|---|---|---|---|
| `Lfp.v` | 69 | 117 | 186 |
| `P037.v` | 149 | 97 | 246 |
| `Correspondence.v` | 49 | 13 | 62 |
| **total** | **267** | **227** | **494** |

## C. Plain-Rocq representation (chosen before porting)

- **Dependencies:** `rocq-core` 9.2.0 (Corelib, including its ssreflect
  tactic files) plus `rocq-stdlib` 9.2.0, used only for `Lia`, `List`
  (`forallb`/`In` lemmas) and `Bool`. Corelib alone has no `lia` and no list
  or arithmetic lemma library; re-deriving them would inflate the port
  artificially, and no real Rocq project works without Stdlib. **Not
  used:** MathComp, Hierarchy Builder, elpi.
- **Coordinates:** a 5-field record `{ix; ix_eqb; ix_eqbP; ix_enum;
  ix_enumP}` for "a type with decidable equality and a complete
  enumeration". This is the minimal finType replacement, and it holds for
  any finite type of any size.
- **State:** a plain function `I -> L`. Equality of states is pointwise
  (`x =1 y`) and is decided by `forallb` over `ix_enum`. The rank sum is a
  fold over `ix_enum`. No `functional_extensionality`, no
  `proof_irrelevance`.
- **Theorem parity under this representation:** MathComp's `x = y` on
  `{ffun}` *is* pointwise equality (`ffunP`). So `jacobi … = Some lfp`
  becomes `∃ x, jacobi … = Some x ∧ x =1 lfp`. Observers only ever apply a
  state, so this is the same guarantee, and the note states it
  explicitly for each theorem. Monotonicity already implies that `F`
  respects `=1` (via antisymmetry), so no extra hypothesis is added.
- **Cheapest falsifier for this choice:** if the generic support (index
  record, state equality, witness extraction, rank sum, reflection glue)
  exceeds ~60 lines before any solver lemma is ported, or if any headline
  theorem needs an axiom, then record a bad signal early. `Print
  Assumptions` must stay empty.

## Decision rule (frozen before the port; copied from the gate's ruling)

- **KILL MATHCOMP (keep Rocq)** if the plain port stays axiom-free, keeps
  the same theorem statements and generality, keeps the same seam and the
  same negative-control sensitivity, **and** handwritten model + proof is at
  most 30 % larger than MathComp's: **≤ 642 lines, i.e. ≤ +148**.
- **KEEP MATHCOMP** if an equivalent plain port needs a new logical axiom,
  or needs > 30 % more handwritten model + proof, or makes finite-state
  equality / rank reasoning materially harder, or makes maintainability
  visibly worse on the concrete diff. The note then records exactly which
  cost MathComp removed.
- **INCONCLUSIVE** only for an external or toolchain blocker that prevents
  an honest comparison within budget.
- **Budget:** ≤ 300 handwritten new or changed `.v` lines. Generated tables,
  comments and shell glue are not counted.
- **Mutants that must still die:** R1, R3, R6, R7, D1, D2, D3, D4. The
  others are kept if they transfer almost for free.

## D. Exact theorem parity

| #367 (MathComp) | plain control | parity |
|---|---|---|
| `jacobi_is_lfp : jacobi N.+1 sbot = Some lfp` over `{ffun I -> L}` | `jacobi_is_lfp : ∃ x, jacobi (S N) sbot = Some x ∧ x =1 lfp` over `I -> L` | equal: `=` on `{ffun}` *is* `=1` (`ffunP`); observers only apply states |
| `lfp_least` (below every **pre**-fixpoint) | same statement | identical |
| `chaotic_is_lfp` for `∀ i, i \in sched` | same with `∀ i, In i sched`, conclusion as above | equal |
| `lax_simulation_lfp` with `alpha sbot = sbot` | `alpha sbot =1 sbot` | equal (same `=1` reading) |
| `N = #|I| * h` | `N = length (ix_enum I) * h` | equal for a duplicate-free enumeration; for any enumeration it is still a valid (larger) bound |
| coordinate type: any `finType` | any `finIx` (decidable `=` + complete enumeration) | equivalent: each gives the other |
| `k10_jacobi`, `k10_least`, `k10_chaotic`, `unfair_schedule_returns_bot`, `lfp_above_seed`, `gt2a_one_step` | same, same generality | identical modulo the `=1` form |
| `gt2a_lfp : tjoin … == collapse …` (bool) | `tjoin … = collapse …` (Prop) | equal (`eqP`) |
| `chain_lfp` (certificate checker) | same; Stdlib's `last` argument order | identical |
| `tables_match_rust`, `constants_match_rust`, `k10_rust_bound`, `vectors_match_rust`, `rust_answers_are_rocq_lfps` | same tables, same 300 vectors, same statements | identical |
| `Print Assumptions` (10 headline theorems) | 10× "Closed under the global context" | identical |

The monotone step already respects `=1` (`F_ext`, via antisymmetry). So the
plain generic theory has **no hypothesis MathComp's lacks**.

## E. Cost comparison

Same counter (`formal/plain-rocq-control/loc.py`) on both sides; code lines
only (non-blank, outside comments):

| file | MathComp model | MathComp proof | plain model | plain proof | plain new/changed |
|---|---|---|---|---|---|
| `Lfp.v` | 69 | 117 | 87 | 135 | 143 |
| `P037.v` | 149 | 97 | 136 | 102 | 120 |
| `Correspondence.v` | 49 | 13 | 58 | 14 | 54 |
| **total** | **267** | **227** | **281** | **251** | **317** |

| dimension | MathComp #367 | plain Rocq control |
|---|---|---|
| handwritten model LOC | 267 | 281 (+14) |
| handwritten proof LOC | 227 | 251 (+24) |
| model + proof | 494 | **532 (+38, +7.7 %)** |
| generic-support boilerplate (approximate; items listed below) | ≈ 60: `'I_k` bijections + `HB.instance` for 5 enums, `Equality.copy` × 3, `sleP`, bigop rank sum, literal-ordinal `ord3` | ≈ 80: `finIx` record, `forallb_false`, `sum_le/lt`, `rank_le`, `seq_eq`/`seq_eqP`/`seq_eq_congr`, `F_ext`, `Scheme Equality` × 7 + `teqP`/`ceqP`, `last_cons`, `peq`/`memb`, `c3` index |
| generated LOC | `RustTables.v` 912 | the same 912, sed-retargeted (2 lines) |
| glue | `check.sh`, `run_mutants.py` | same shape (`check.sh` + sed, `run_mutants.py` with mutation sites re-spelled) |

Where MathComp's `{ffun}` / `bigop` value sat, as expected: generic support
is about 20 lines larger without them. The rest of the delta (+18) is proof
bookkeeping for pointwise equality in the chaotic invariant (`grows`) and
`exists x … ∧ x =1 lfp` statements. No new framework, no library of finite
maps, orders or fixpoints was needed.

## F. Seam parity

- The exporter `formal/mathcomp-spike/export/` is **unchanged**.
  `check.sh` and the mutant runner rewrite only its two `Require` lines
  (`From mathcomp Require Import boot.` → `From Stdlib Require Import
  List.`, `P037Spike` → `PlainSpike`). The rows are byte-identical.
- The generated file uses MathComp's `[:: …]` list syntax. The plain model
  defines the two notations (`[:: ]`, `[:: x1 ; .. ; xn ]`) and
  `seq := list` in 3 lines instead of changing the generator.
- Same checks: full-domain agreement **and** coverage for `join`,
  `fin`/`lower`, `collapse`, `contribute ∘ read` and `apply`; the height
  constants; 300 Rust Jacobi chains for `sys` and for `sys.collapsed()`
  replayed through the proved `chain_lfp`.

## G. Mutants

`python3 formal/plain-rocq-control/mutants/run_mutants.py` gives
**11/11 KILLED**, and each is rejected by the *same* lemma as in #367:

| id | MathComp rejects at | plain rejects at |
|---|---|---|
| R1 non-commutative join | `tjoinC` | `tjoinC` |
| R2 "must wins" join | `crank_ok` | `crank_ok` |
| R3 unsafe apply (unfinalized) | `k6_ok` | `k6_ok` |
| R4 dynamic split | `contrib_mono_ok` | `contrib_mono_ok` |
| R5 fabricated must | `contrib_mono_ok` | `contrib_mono_ok` |
| R6 fairness dropped | `chaotic_is_lfp` | `chaotic_is_lfp` |
| R7 bound `n·h` | `jacobi_is_lfp` | `jacobi_is_lfp` |
| D1 kernel "must wins" | `tables_match_rust` | `tables_match_rust` |
| D2 kernel `collapsed()` keeps masks | `vectors_match_rust` | `vectors_match_rust` |
| D3 kernel `step()` drops seed | `vectors_match_rust` | `vectors_match_rust` |
| D4 kernel `neg` without swap | `tables_match_rust` | `tables_match_rust` |

## H. Dependency / toolchain comparison (MEASURED, same container)

| | MathComp #367 | plain Rocq control |
|---|---|---|
| Rocq packages | `rocq-core` + `rocq-mathcomp-boot` + `rocq-mathcomp-order` + `rocq-hierarchy-builder` + `rocq-elpi` | `rocq-core` + `rocq-stdlib` |
| opam closure | 46 packages; **32 beyond the shared base**: elpi, rocq-elpi, HB, MathComp, plus atd/atdgen/atdts, ppxlib/ppx_deriving/ppx_optcomp, the menhir family, sexplib0, yojson, … | 14 packages; **+1** (`rocq-stdlib`) |
| disk (installed `.vo`/libs) | mathcomp 44 MB + HB 2.4 MB + elpi user-contrib 37 MB + `lib/elpi` 75 MB + `lib/rocq-elpi` 30 MB ≈ **190 MB** | Stdlib **73 MB** |
| install time | MathComp boot+order 214 s, plus elpi/rocq-elpi/HB (inside a 173 s run that also built rocq-core; not separable) | `rocq-stdlib` 191 s |
| clean install steps | switch + repo add + `opam install rocq-core.9.2.0 rocq-mathcomp-boot.2.6.0 rocq-mathcomp-order.2.6.0` | switch + repo add + `opam install rocq-core.9.2.0 rocq-stdlib.9.2.0` |
| proof/check wall time | Lfp 1.4 + P037 1.9 + RustTables 3.1 + Correspondence 2.3 = **8.7 s** | 0.8 + 1.6 + 2.0 + 0.6 = **5.0 s** |
| assumptions | none | none |
| computability traps met | `inord`/`insub` via opaque `idP`; locked `card`/`enum`/`{ffun}`; `[forall]` | none (plain functions and lists all reduce) |
| churn observed | 2.5 split packages; 2.6 deprecated `all_boot` → `boot`, renamed packages, changed rewrite order | Stdlib split from Corelib in 9.0; stable since |

## I. Decision against the pre-registered gate

| criterion | observation | met |
|---|---|---|
| axiom-free | 10 headline theorems "Closed under the global context" | yes |
| same theorem statements / generality | §D; the only change is `=` on `{ffun}` read as `=1` | yes |
| same seam | unchanged exporter, same tables, same 300 certified traces | yes |
| same negative-control sensitivity | 11/11, same rejecting lemmas | yes |
| model + proof ≤ +30 % (≤ 642) | **532 (+7.7 %)** | yes |
| KEEP triggers: new axiom / > 30 % / materially harder finite-state or rank reasoning / visibly worse diff | none. Finite-state equality costs ~20 lines of generic support and some `=1` bookkeeping, measured and small | none fired |
| budget ≤ 300 new/changed `.v` lines | 317 | **overrun, +17** (declared; mechanical renames) |

**Decision: KILL MATHCOMP. KEEP Rocq.** The MathComp / HB / elpi
dependency surface does not pay for itself on this development. What
MathComp removed here (about 20 lines of finite-index and sum support) is
smaller than what it adds: a 32-package toolchain closure, computability
traps and version churn.

Not decided here, by ruling: whether the generic theory is reusable (the
election instance, K10e). That is the next separate gate, and it would now
run on the plain-Rocq variant.
