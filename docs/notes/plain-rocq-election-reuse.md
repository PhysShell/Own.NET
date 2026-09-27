# Election reuse gate for the plain-Rocq solver theory (#369)

> **REUSE GATE FOR: #369.** Status: **PRE-REGISTERED, no `.v` written yet.**
> RESULT: _filled after the experiment._

## Research question

> Is the generic plain-Rocq solver theory of #369 (`Lfp.v`) really reusable,
> or was the P-037 transfer solver its one lucky instance?

It is tested on the election pre-solver of G-S1 (K10e). No production
functionality is added, and #367 and #369 are not modified.

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
