# Election reuse gate for the plain-Rocq solver theory (#369)

> **REUSE GATE FOR: #369.**
> **RESULT: KEEP GENERIC ROCQ THEORY.**
> **Lfp.v changed: NO. Changed LOC: 0.**
>
> The research question and §B–§C were committed in `3f8435c` before any
> `.v` code existed. §A and §D–§J were added after the experiment.

## Research question

> Is the generic plain-Rocq solver theory of #369 (`Lfp.v`) really reusable,
> or was the P-037 transfer solver its one lucky instance?

It is tested on the election pre-solver of G-S1 (K10e). No production
functionality is added, and #367 and #369 are not modified.

## A. RESULT

**KEEP GENERIC ROCQ THEORY.** The election pre-solver gets unbounded K10e as
an instantiation of the unchanged `Lfp.v`:

- **`Lfp.v`: 0 changed lines.** No new solver proof, no new helper.
  `k10e_jacobi`, `k10e_least` and `k10e_chaotic` are each **one `exact:`**
  of `jacobi_is_lfp` / `lfp_least` / `chaotic_is_lfp`.
- **Size: 111 / 180** new `.v` code lines: `Election.v` 104 (58 model, 46
  proof) and `ElectionAudit.v` 7. That is half of the generic theory's 222
  lines, and most of it is the lattice itself, not solver work.
- **Unbounded K10e.** Any finite coordinate type, any edge count, any fair
  schedule, and the `n·2 + 1` pass bound, over **any guard type with
  decidable equality**. Kani's harnesses cover n ≤ 3 (Jacobi) and n = 2 with
  ≤ 1 edge (chaotic) over `u8` guards.
- **No frontend hypothesis.** `estep_mono` follows from `le_join2` (generic)
  and `import_mono` alone, with no `well_formed`, G-V4 or CFG hypothesis.
- **Axiom-free**, and **4/4 negative controls killed**, each by the
  semantically right lemma.

## B. Pre-registered gate

**Base:** `1bfd5ed16c5c6f1ffa257b4091770d1dedd7778c` (head of #369). The
branch is `research/plain-rocq-election-instance`, and its PR goes against
`research/plain-rocq-control`.

**Necessary conditions** (all must hold):

- **R1 — no generic redesign.** `Lfp.v` is used as is. A small, obviously
  generic helper is allowed only if the instance would otherwise be
  artificially contorted; any such change is a bad signal and is reported
  as "Lfp.v changed: YES".
- **R2 — thin instance.** The instance consists of: carrier, bot, join,
  equality, rank/height, laws, `import`, step, and step monotonicity. No
  framework for flat lattices.
- **R3 — unbounded K10e.** Any finite coordinate type, any edge count, Jacobi
  reaching the lfp within `n·HEIGHT + 1` passes with HEIGHT = 2, the least
  pre-fixpoint, and every fair chaotic schedule reaching the same lfp.
- **R4 — no frontend assumption.** No G-V4, Roslyn, CFG or `well_formed`
  hypothesis. Step monotonicity must follow from the join and the
  monotonicity of `import` alone.
- **R5 — cheap second application.** Well below the first generic
  development: the #369 `Lfp.v` has 222 code lines.

**Cheap falsifiers:**

| condition | falsifier |
|---|---|
| R1 | any semantic change to `Lfp.v`, or a new Jacobi/chaotic/lfp proof for elections |
| R2 | the instance needs more than a handful of law/rank lemmas, or a lattice library |
| R3 | a headline theorem is stated for a fixed `n`, fixed edge count or fixed schedule |
| R4 | `step_mono` needs a hypothesis about the system beyond the algebra |
| R5 | the instance approaches the 180-line cap |

**Hard budget:** at most **180** new or changed handwritten `.v` code lines,
counting `Lfp.v` modifications. This is enforced by
`formal/plain-rocq-control/election_loc_gate.py`, which runs throughout the
work. When it reaches 180 with an unfinished instance: **STOP, RESULT: KILL
GENERIC REUSE**. There is no after-the-fact "mechanical lines" argument.
Generated data, README and notes are not counted.

**Hard KILL:** any of these:

- `Lfp.v` needs a substantive change;
- the generic theorems cannot simply be instantiated;
- more than 180 lines;
- a new axiom;
- an election-specific solver framework;
- frontend or G-V4 assumptions;
- most of the work repeats `Lfp.v`.

**KEEP GENERIC ROCQ THEORY** only if `Lfp.v` is practically unchanged, the
adapter is small, K10e is unbounded, everything is axiom-free, the negative
controls die, and the count is ≤ 180.

## Intended instance shape

- `Election G := ENone | One (g : G) | Conflict`, over any `G` with
  decidable equality. This is more general than Rust's `u8` guards, and
  needs no enumeration of guards.
- Join: `ENone` is the identity, `Conflict` absorbs, `One g ⊔ One h` is
  `One g` if `g = h` and `Conflict` otherwise. The rank is 0, 1, 2 (height
  2).
- `import`: `ENone ↦ ENone`, `Conflict ↦ Conflict`, and `One h` under
  `Id`/`Neg {callee = c, caller = g}` maps to `One g` if `h = c` and to
  `ENone` otherwise. `Const` and `Opaque` map to `ENone`.
- Proved about `import`: only monotonicity, plus pins. It maps exactly the
  bound guard (K4). It is **not** a join morphism (the F3 witness).
- System: a seed plus an arbitrary list of `(callee, binding)` edges per
  coordinate. Step = seed ⊔ the imports, folded left to right (as in Rust).
- K10e: instantiate `jacobi_is_lfp`, `lfp_least` and `chaotic_is_lfp` from
  `Lfp.v`.

**Negative controls:**

- E1: a broken flat join (`One g ⊔ One h ≠ Conflict` for `g ≠ h`);
- E2: a non-monotone import (`Conflict ↦ ENone`);
- E3: a wrong binding (`One h ↦ One caller` regardless of `h = callee`);
- E4: the fairness hypothesis removed from the chaotic theorem.

**Scope:** the Rocq theorem is about the *transcribed* Election semantics.
Kani stays the check of the real Rust code (bounded). No Rust↔Rocq election
seam is required. One may be added only if it costs ≤ ~30 lines and
fits the cap.

## C. Kani baseline (REPOSITORY FACT, `formal/p037-kernel/src/properties/election.rs`; times from `p037-formal-kernel.md` §3)

| harness | bound |
|---|---|
| `k4_import_is_monotone_and_conflict_propagates` | all values (`u8` guards) |
| `k10e_election_step_is_monotone_in_the_state` (3.9 s) | n = 3, ≤ 2 edges, symbolic state |
| `k10e_elect_is_a_fixpoint_below_every_fixpoint` (24 s) | n = 3, ≤ 2 edges |
| `k10e_chaotic_equals_jacobi_on_small_sccs` (44 s) | n = 2, ≤ 1 edge, schedule of length 3 |

The `cargo test` twins add 20 000 random systems with n ≤ 3, the §8 row-11
pin, and the pins that import is not a join morphism and maps exactly the
bound guard.

## Deviation carried over from #369 (recorded here; #369 is frozen)

#369's pre-registered budget was **≤ 300** new or changed `.v` lines. It
used **317**. **This is a protocol deviation of +17 lines.** It does not
change #369's comparative result (532 vs 494; a +30 % threshold of 642), but
the budget was a maximum and it was exceeded. #369's note calls the overrun
"mostly mechanical"; that explanation does not make it compliant.

## D. Election instance (`formal/plain-rocq-control/theories/Election.v`)

| component | code lines | content |
|---|---|---|
| header | 9 | imports, section variables `G`, `geqb`, `geqP` |
| lattice | 40 | `election`, `ejoin`, `eeqb` + `eeqP`, `erank`, the four join laws, `erank_lt`, `erank_h` |
| import | 25 | `binding`, `import`, `import_mono`, pins `import_bound`, `import_unbound`, `import_not_join_morphism` |
| system + K10e | 30 | `esys` (seed + arbitrary edge list), `estep` (Rust fold order), `EF`, `estep_mono`, four headline results |

The model transcribes `formal/p037-kernel/src/lib.rs` (`Election::join`,
`import`, `ElectionSystem::step`). Two things generalize it: guards are
any `G` with decidable equality instead of `u8`, and the edge list is
arbitrary instead of `[Option<ElectionEdge>; 2]`. The most awkward proof
was associativity with three `One` guards (7 lines), which is the price of
a generic `G`. Nothing needed a flat-lattice library.

## E. Generic-theory reuse

| generic result (`Lfp.v`, #369) | election use | new proof written |
|---|---|---|
| `jacobi_is_lfp` | `k10e_jacobi` | none: `exact:` with the 7 instance facts |
| `lfp_least` | `k10e_least` | none |
| `chaotic_is_lfp` | `k10e_chaotic` | none |
| `le_join2`, `le_refl` | `estep_mono` | a 6-line fold induction, the same shape as `P037.step_mono` |
| `finIx`, `sle`, `sbot`, `jacobi`, `chaotic`, `lfp` | the statements | none |

The instance paid only for local facts: 4 join laws, a decidable equality,
the rank bound (2) and strictness, import monotonicity, and step
monotonicity. This is exactly the division of labour the gate hoped for.

## F. Theorem results

| theorem | statement | Kani counterpart (bound) |
|---|---|---|
| `estep_mono` | the step is monotone in the state, for any system | `k10e_election_step_is_monotone_in_the_state` (n = 3, ≤ 2 edges) |
| `k10e_jacobi` | `∃ x, jacobi (|I|·2 + 1) ⊥ = Some x ∧ x =1 lfp` | `k10e_elect_is_a_fixpoint_below_every_fixpoint` (n = 3, ≤ 2 edges) |
| `k10e_least` | `lfp ≤` every pre-fixpoint | the same harness, "below every fixpoint" |
| `k10e_chaotic` | every schedule covering all coordinates (repeats allowed) returns the same lfp within `|I|·2 + 1` passes | `k10e_chaotic_equals_jacobi_on_small_sccs` (n = 2, ≤ 1 edge, length 3) |
| `k10e_unfair_returns_bot` | an empty schedule returns ⊥: fairness is necessary (same class as #368) | assumed by the harness |
| `import_mono` | K4 monotonicity for every binding | `k4_import_is_monotone_and_conflict_propagates` (all `u8` values) |
| `import_bound`, `import_unbound` | exactly the bound guard is imported | `k4_import_maps_exactly_the_bound_guard` (pins) |
| `import_not_join_morphism` | `h ≠ h'` ⇒ `import (One h ⊔ One h') = Conflict`, but the joined imports give `One g` (the F3 witness) | the pin in the `k4_…` twin |

**Scope, stated as ruled.** These are unbounded theorems about the
*transcribed* election semantics. Kani remains the bounded check of the
*actual* Rust code. No Rust↔Rocq election refinement is claimed, and no
seam was added (none was required, and none was needed to decide the gate).

## G. Negative controls

`python3 formal/plain-rocq-control/mutants/run_election_mutants.py` gives
**4/4 KILLED**:

| id | mutation | rejected by |
|---|---|---|
| E1 | `One g ⊔ One h = One g` even for `g ≠ h` | `ejoinC` |
| E2 | `Conflict` imports as `ENone` | `import_mono` |
| E3 | `One h` imports as `One caller` regardless of `h = callee` | `import_unbound` |
| E4 | fairness hypothesis weakened to `In i sched ∨ True` | `k10e_chaotic` |

A first run showed E3 rejected by `import_bound` instead. That lemma is
still *true* under E3; its proof script merely failed a `rewrite`. The
proof was made robust (`?geqxx`), so the kill now comes from the lemma that
is actually false. This is recorded so the non-vacuity claim is not a
proof-script artefact.

## H. LOC / check cost / assumptions

| item | value |
|---|---|
| `Lfp.v` modifications | **0** |
| `Election.v` | 104 code lines (model 58, proof 46): header 9, lattice 40, import 25, system + K10e 30 |
| `ElectionAudit.v` | 7 |
| **total new/changed `.v`** | **111 / 180** (`election_loc_gate.py`: OK) |
| generic theory it reuses | `Lfp.v`, 222 code lines, written once in #369 |
| check time | `Election.v` 0.6 s (the whole `check.sh` ≈ 6 s) |
| assumptions | `k10e_jacobi`, `k10e_least`, `k10e_chaotic`, `estep_mono`, `import_mono`, `import_not_join_morphism`: all "Closed under the global context" |

## I. Exact changes required in `Lfp.v`

**None.** `git diff 1bfd5ed -- formal/plain-rocq-control/theories/Lfp.v` is
empty.

## J. Decision

| pre-registered condition | observation | met |
|---|---|---|
| R1 no generic redesign | `Lfp.v` unchanged; no solver proof re-done | yes |
| R2 thin instance | carrier, join, equality, rank, laws, import, step, step monotonicity; no lattice library | yes |
| R3 unbounded K10e | any `finIx`, any edge list, any fair schedule, bound `|I|·2 + 1` | yes |
| R4 no frontend assumption | `estep_mono` needs only the algebra | yes |
| R5 cheap second application | 111 lines against the 222-line generic theory; 0 lines of solver proof | yes |
| ≤ 180 lines | 111 | yes |
| axiom-free | yes | yes |
| negative controls | 4/4 | yes |
| any hard KILL rule fired | none | — |

**RESULT: KEEP GENERIC ROCQ THEORY.** `Lfp.v` was written once, and the
second Own.NET solver received unbounded K10e by instantiation, paying only
for its local lattice and monotonicity facts. The architecture this points
to has two layers:

- Kani for the real, bounded Rust code;
- Rocq, once, for the algorithmic properties of any finite-height monotone
  solver; each concrete solver then contributes only local lemmas.

Stopped here, as ruled. Not done: a Rust↔Rocq election seam, G-T2b, A1,
#368, CI.
