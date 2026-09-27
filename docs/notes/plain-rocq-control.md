# Plain-Rocq control for the MathComp spike (#367)

> **CONTROL FOR: #367.** Status: **PRE-REGISTERED, port not started.**
> Result: _filled after the port._
> Rocq status: **KEEP** (#367 established it; not the subject of this gate).

The only question here:

> If MathComp is removed, does proving the same Own.NET guarantees become
> costly or weak enough that the MathComp dependency pays for itself?

Out of scope, by ruling: the election instance (K10e), new theorem targets,
any P-037 extension, the `solve_with` fairness defect (filed as #368), and
production code.

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
