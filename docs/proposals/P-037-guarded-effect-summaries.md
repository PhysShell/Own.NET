# P-037 — Guarded effect summaries: the conditional-transfer contract for #304

Status: **draft** (design-only; implementation is post-cutover, #304 / P-036
Phase 2 — the P-022 verdict-changing freeze applies until then).

Related work:

- [`spec/Inference.md`](../../spec/Inference.md) — the base lattice and the
  INF-rule vocabulary this proposal extends (nothing here replaces it);
- [P-036](P-036-interprocedural-semantic-architecture.md) — names the MVP
  guarded-effects policy this proposal formalizes (ownership-summary section);
- #304 — the post-cutover tracker whose core contract this is;
- #305 / [`docs/notes/teardown-predicate-adversarial-audit.md`](../notes/teardown-predicate-adversarial-audit.md)
  — the extractor-side bounded fixes whose general answer this is;
- [`docs/notes/interprocedural-tz.md`](../notes/interprocedural-tz.md) — D1/D6/D7,
  the conservatisms this proposal is allowed to refine.

## 0. Decision in one paragraph

Extend the per-parameter transfer summary from a single `Transfer` value to a
**guarded transfer**: either unconditional (today's value) or a **single fixed
split** over one boolean/null-ness predicate of the same method's own parameter
list, with a `Transfer` value per side. The split variable is chosen
**deterministically at derivation time, before the solver runs**; the fixpoint
then operates in the plain product lattice `Transfer × Transfer`, where join is
cellwise and every solver property (monotonicity, associativity, termination,
order-independence) is inherited componentwise from the base lattice. Call
sites that pass a statically-known constant select a cell; everything else
joins the cells and behaves exactly like today. Collapsing the split recovers
today's summary (a proven refinement, §7), so the layer degrades to the current
behavior everywhere the guard vocabulary does not apply — and the flagship
`Teardown(bool)` / null-guard-helper cases stop falling through the
architecture.

## 1. Motivation — the bool that beat a thousand lines

The heap-proven SectorTS shape (#278, #305):

```csharp
void Teardown(bool skip)
{
    if (!skip)
        publisher.Event -= handler;    // the release
}

Teardown(true);                        // never releases
Teardown(false);                       // always releases
```

Today's context-insensitive MOS (INF-S2) can only say `may` — true and
useless: both call sites lower to plain + OWN051 (INF-A1/A5), and the caller
that provably leaks is exactly as silent as the caller that provably releases.
The #305 extractor predicates close the *reported* instances lexically, but
they are extractor-side special cases; the summary layer itself cannot express
the distinction. P-036 committed to an MVP policy ("summaries preserve guarded
effects over simple boolean/null predicates; callsites substitute known
constants; everything else degrades to May/Unknown, never Must") — this
proposal is that policy made precise enough to implement and to review.

A second motivator is the **D1 conservatism**: the null-guard helper
`void Close(Stream s) { if (s != null) s.Dispose(); }` derives `may` today
(partial release, INF-S2) and unchecks the caller (INF-A5). With a self-null
split, a call site passing a provably non-null argument selects the `must`
cell — the common defensive-helper idiom returns from `plain` to `consume`
without touching the precision floor.

## 2. The guard vocabulary (G-V)

- **G-V1 (guard variables).** A guard variable of method `M` is either
  - a **boolean parameter** `p` of `M` (split sides: `p == true` / `p == false`), or
  - the **null-ness of a reference parameter** `q` of `M` (split sides:
    `q != null` / `q == null`). `q` may be the summarized disposable parameter
    itself (the *self-null* split, §4).
- **G-V2 (one literal, no conjunctions).** A guarded action carries **at most
  one** guard literal. Conjunctions, disjunctions, comparisons against
  non-literals, field/local/property conditions, and any predicate over more
  than one variable are **outside the vocabulary** — actions under them derive
  as today (both cells, §4). This is a design wall, not a TODO: every widening
  of the vocabulary multiplies the cell space and reopens the join-collapse
  problem of §3.
- **G-V3 (whose parameters).** Guard variables are parameters of the method
  being summarized — never fields, locals, globals, or the caller's variables.
  A local initialized from a parameter is a local (the laundering case stays
  honest: no claim; cross-ref audit attack C).

## 3. The guarded-transfer lattice (G-L)

### The shape

```text
GuardedTransfer ::= Uncond(t)                      -- today's summary
                  | Split(g, t_pos, t_neg)         -- one fixed split
    t, t_pos, t_neg ∈ Transfer = {⊥, no, must, may, unknown}   (INF-L1/L2)
    g = a guard variable of this method (G-V1)
```

`t_pos` is the transfer when `g`'s positive side holds (`p == true` /
`q != null`), `t_neg` the negative side.

### The load-bearing design decision: fix the split before the solver

A naive design would let the solver join `Split(g, …)` with `Split(g', …)` for
`g ≠ g'` by collapsing to `Uncond`. That join is **not associative**: the
result depends on the order in which mixed-variable summaries meet, which
breaks the least-fixpoint's order-independence (INF-F3, INV8) — the exact
property the whole solver architecture rests on. Therefore:

- **G-L1 (fixed split).** The split variable of a `(method, parameter)` summary
  is chosen **once, deterministically, at derivation time** (§4, G-S1). The
  solver never sees two different split variables for the same cell space: a
  summary is either `Uncond` or `Split` over its one fixed `g`, for its entire
  lifetime.
- **G-L2 (product order).** With `g` fixed, `Split(g, a, b)` is an element of
  the product lattice `Transfer × Transfer` ordered cellwise;
  `Uncond(t)` embeds as `Split(g, t, t)` wherever a cellwise operation needs
  it. Join is cellwise `INF-L1` join. Commutativity, associativity,
  idempotence, and monotonicity are inherited componentwise — there is nothing
  new to prove about the join itself.
- **G-L3 (height).** `Transfer` has height 3 (`⊥ < no|must < may < unknown`,
  with `no`/`must` incomparable). The product has height 6. Every ascending
  chain is finite; termination of the fixpoint follows exactly as today
  (INF-F3), with the iteration bound doubled at worst.
- **G-L4 (⊥ discipline).** Cellwise `⊥` is seed-only, exactly INF-L2: a
  residual `⊥` in either cell finalizes as `no` for that cell.

## 4. Derivation (G-S rules)

Derivation extends `INF-S1–S6` with cell awareness. The walker is the
branch-sensitive machinery D1/D7 already built (`_definite_release`,
`_early_return_before_forward`) — parameterized by cell.

- **G-S1 (split election, deterministic, two stages — both pre-solver).**
  *Stage 1 (own body):* collect every guard literal (G-V1) that lexically
  governs an ownership action on parameter `i` — an enclosing single-literal
  `if`/`else`, or a single-literal-guarded early `return` preceding the action
  (the two shapes #305 pinned).
  *Stage 2 (election propagation):* a parameter of `M` passed through an
  `id`/`neg` argument map (G-S5) into the guard-variable position of a callee
  whose `(callee, param)` already elected a split **imports** that election
  into `M` — propagated over the call graph as a set-valued fixpoint
  (monotone: elections are only ever added; finite: at most one candidate per
  parameter pair; terminates). This is what lets a wrapper that merely
  *forwards* its flag (worked cases 7–8) inherit the split — its own body has
  no governing literal to elect from. Stage 2 uses only elected *variables*
  and argument maps, never solved values, so it completes strictly before the
  value fixpoint and G-L1 holds.
  Then, per `(method, parameter)`:
  - exactly **one** candidate variable (from both stages) → `Split` over it;
  - **zero** → `Uncond` (today's derivation verbatim);
  - **two or more** distinct candidates → `Uncond`, derived as today
    (both-cell semantics; the honest join). Conflict resolution is a pure
    function of the skeleton set — no join ordering can influence it.
- **G-S2 (cellwise definiteness).** Within each cell, `INF-S2/S3` apply with
  paths **restricted to the cell**: a release definite on every normal-return
  path *consistent with the cell's literal* contributes `dispose` to that cell;
  a path that keeps the parameter contributes `borrow` to that cell. The
  canonical shapes and their cells:

  | body shape | positive cell | negative cell |
  |---|---|---|
  | `if (g) { release }` (else: nothing) | `must` | `no` |
  | `if (!g) { release }` | `no` | `must` |
  | `if (g) return; release` | `no` | `must` |
  | `if (!g) return; release` | `must` | `no` |
  | release unconditional | `must` | `must` |
  | release also behind a second, non-vocabulary condition | `may` in that cell | per shape |

- **G-S3 (self-null split).** For a disposable reference parameter `q`, a
  release guarded by `q != null` (or an early `return` guarded by `q == null`)
  derives `Split(null-ness(q), must, no)`: definitely consumed when non-null,
  untouched when null. This single rule retires the D1 `may`-degradation for
  the defensive-helper idiom — *without* weakening D1's protection: the
  unconditional-`must` claim is still never made.
- **G-S4 (guarded forwards).** A forward (`INF-S3`) under a guard literal
  contributes its `forward` edge **to that cell only**; the other cell gets
  what its own paths say (`borrow` if the parameter is kept there, nothing if
  unused). The straight-line/early-return conditions of INF-S3 apply per cell.
- **G-S5 (transform on the edge).** A forward edge records how the caller's
  cells map to the callee's, as one of five transforms:
  `const-pos` / `const-neg` (a literal argument), `id` (the caller's own split
  variable passed through), `neg` (passed through negated: `Inner(!keep)`),
  `opaque` (anything else). `id`/`neg` are recognized only when caller and
  callee split variables correspond through that same argument position.
- **G-S6 (everything else).** Actions not covered by G-S1–G-S5 derive exactly
  as today. In particular explicit `effect` contracts (INF-S1) remain
  unconditional and win over inference in both cells.

## 5. The solver (G-F rules)

- **G-F1 (cellwise fixpoint).** The SCC condensation, seeding, and iteration
  are INF-F1–F3 verbatim, over the product lattice. Since the split is fixed
  per summary (G-L1), "cellwise" is well-defined throughout.
- **G-F2 (edge resolution through transforms).** Resolving a forward edge with
  transform τ reads the callee's summary as follows:
  - `const-pos` → the callee's positive cell; `const-neg` → negative cell;
  - `id` → positive-to-positive, negative-to-negative; `neg` → crosswise;
  - `opaque` → the join of the callee's cells (exactly today's read).
  Each is a monotone function of the callee summary: projections and the
  cell-swap are monotone in the product order, and join is monotone. Hence the
  global transfer function stays monotone and the least fixpoint exists and is
  order-independent — the INF-F3 argument goes through unchanged.
- **G-F3 (overload merge).** `INF-M1–M3` act before solving, as today, with one
  addition: overloads whose elected splits differ (including Split vs Uncond)
  merge by **collapsing every side to `Uncond` first** (G-T2's collapse), then
  joining as today. Deterministic — the merge happens once, pre-solver, so
  G-L1 is preserved.
- **G-F4 (degradation).** INF-F5–F7 apply unchanged; wherever they yield
  `unknown` today they yield cellwise `unknown` now. A solve failure degrades
  the whole layer with OWN052 exactly as before.

## 6. Application at the call site (G-A rules)

- **G-A1 (cell selection).** At a call site, for a `Split(g, …)` summary:
  - the argument bound to `g` is the literal `true`/`false`, or `null`, or a
    provably non-null expression (a fresh `new`/factory result already tracked
    as owned — nothing subtler) → **select** the corresponding cell and lower
    it by `INF-A1` (`must → consume`, `no → borrow`, `may`/`unknown → plain` +
    OWN051);
  - anything else → lower `join(t_pos, t_neg)` by INF-A1 — byte-for-byte
    today's behavior.
- **G-A2 (the floor, restated for cells).** A `consume` may be applied **only**
  from a cell whose value is `must` **and** whose selection is proven by G-A1's
  static test at *this* call site. No cross-call-site inference, no "most
  callers pass true", no default cell. An unselected `Split` never applies a
  cell alone.
- **G-A3 (borrow cells are findings, not favors).** Selecting a `no` cell keeps
  the obligation with the caller — where today's `plain` + OWN051 silenced it.
  `Teardown(true)` therefore surfaces the honest OWN001. This is the intended
  verdict change of #304 Phase 2, and the reason the whole layer is gated
  behind the cutover, not slipped into a patch release.
- **G-A4 (consume cells discharge for real).** Selecting a `must` cell applies
  `consume`: a defensive dispose *after* `Teardown(false)` is now a true
  OWN003/OWN002 — the callee provably disposed on that path. Same doctrine as
  the unconditional-consume control in the D1 test matrix.
- **G-A5 (advisory hygiene).** OWN051 is emitted only where lowering actually
  degrades (`may`/`unknown` after selection-or-join). A selected `must`/`no`
  cell is a *verified* contract — no advisory. Guarded summaries strictly
  shrink the OWN051 surface; they never add to it.
- **G-A6 (untrack interplay).** INF-A5a/A5b apply after G-A1 exactly as today,
  but on the post-selection value. Cells resolved to `must`/`no` bypass the
  untrack channel entirely — each call site that G-A1 decides removes one
  instance of the documented D6 whole-body-untrack residual.

## 7. The two theorems the review must check (G-T)

- **G-T1 (precision floor).** *No rule in this proposal fabricates a `must`,
  `fresh`, or alias claim.* Proof obligation, by construction: a cell reaches
  `must` only through cell-definite release (G-S2/G-S3: definite on every path
  consistent with the cell) or through a forward chain of such cells (G-F2
  reads are monotone selections, and `must` survives only if the source cell
  was `must`); and `must` is *applied* only under G-A2's static selection.
  Every non-vocabulary shape, laundered guard, mixed split, opaque transform,
  or unknown argument lands on a join — which is today's value. The floor
  (`own-only 0`, INF §"The floor") is preserved verbatim.
- **G-T2 (refinement / compatibility).** Define
  `collapse(Uncond(t)) = t`, `collapse(Split(g, a, b)) = join(a, b)`.
  Then:
  1. **Derivation compatibility:** for every body, `collapse` of the guarded
     derivation equals today's derivation. (G-S2's cells partition exactly the
     paths INF-S2 already walks: definite-in-both-cells joins to `must`,
     definite-in-one joins to `may` — the same `[dispose, borrow]` INF-S2
     emits for a partial release. G-S1's zero-and-many cases are today's
     derivation by definition.)
  2. **Solver refinement:** `collapse` is a join-morphism on the product
     lattice, and every G-F2 edge read laxly commutes with it (a selected or
     mapped cell is ≤ the join of cells). Hence
     `collapse(lfp guarded) ≤ lfp(collapsed)` — the guarded fixpoint is never
     *coarser* than today's, and wherever no guard information exists it is
     equal (by 1 and monotonicity).
  3. **Application compatibility:** with no static selection, G-A1 lowers the
     collapse — today's behavior exactly.
  Consequence for migration: the summary dump gains the split as an additive
  field plus a derived collapsed view; diffing the collapsed view against
  today's golden dumps isolates exactly the intended Phase-2 verdict changes,
  and nothing else.

## 8. Worked adversarial cases (hand-derived; the conformance seeds for #304)

Notation: `S = Split(g, pos, neg)`; call-site column shows the applied effect.

| # | case | summary | call site | applied |
|---|---|---|---|---|
| 1 | `Teardown(bool skip){ if(!skip) release p; }` | `Split(skip, no, must)` | `Teardown(true)` | `borrow` → caller keeps obligation → honest OWN001 |
|   |   |   | `Teardown(false)` | `consume` → silent; later defensive dispose = true OWN003 |
|   |   |   | `Teardown(x)` (unknown) | `join = may` → plain + OWN051 (today) |
| 2 | same body, early-return spelling `if (skip) return; release p;` | identical by G-S2 row 3 — the two spellings converge in the summary, closing the asymmetry #305-A closed lexically | — | — |
| 3 | `Dispose(bool d)` canonical: release under `if (d)` | `Split(d, must, no)` | `Dispose(true)` | `consume` |
|   | release misplaced in `else` | `Split(d, no, must)` | `Dispose(true)` | `borrow` → OWN001 (the #305-B verdict, now from the summary itself) |
| 4 | null-guard helper `Close(Stream s){ if (s!=null) s.Dispose(); }` | self-null: `Split(nn(s), must, no)` | arg = tracked fresh stream | `consume` (D1 conservatism retired for this idiom) |
|   |   |   | arg nullable/unknown | `join = may` → plain + OWN051 (D1 behavior kept) |
| 5 | laundering: `bool t = skip; if (!t) release p;` | guard is a local ⇒ G-V3 ⇒ `Uncond(may)` | any | today's behavior — no claim (audit attack C stays honest) |
| 6 | two variables: `if (a) release p; if (b) release p;` | G-S1 many ⇒ `Uncond` derived as today (`may`) | any | today's behavior |
| 7 | wrapper `Outer(bool keep){ Inner(keep); }`, `Inner = Split(keep, no, must)` | split imported by G-S1 stage 2 (no own-body literal!), edge transform `id` ⇒ `Outer = Split(keep, no, must)` | `Outer(false)` | `consume` — the guard survives one hop |
| 8 | negation wrapper `Outer(bool stop){ Inner(!stop); }` | stage-2 import, transform `neg` ⇒ cells swap ⇒ `Split(stop, must, no)` | `Outer(true)` | `consume` |
| 9 | alternating recursion `F(p, bool g){ if (g) release p; else F(p, !g); }` | seed `(⊥,⊥)`; iter 1: pos `must`, neg reads pos through `neg` ⇒ `must`; iter 2: fixpoint `Split(g, must, must)` = collapse `must` — correct: every execution releases; terminates in 2 iterations (G-L3 bound respected) | any | `consume` |
| 10 | disagreeing call sites `Teardown(true)` + `Teardown(false)` in one program | one summary, per-site selection (G-A1) — no cross-site contamination; each site gets its own row-1 verdict | — | — |

Each row is a fixture family for #304's conformance vectors; rows 1–3 are the
summary-level twins of the corpus cases #305 landed, and must agree with them.

## 9. Non-goals (walls, not TODOs)

- no conjunctions/disjunctions or multi-variable predicates (G-V2);
- no field/local/property guards, no guard state threading (G-V3);
- no guard propagation beyond the single-edge transforms of G-S5 — in
  particular no caller-of-caller constant folding;
- no symbolic execution, no path conditions, no SMT;
- no per-call-site summary specialization (the summary stays one object; only
  *selection* is per-site);
- no change to the strict/optimistic reporting policy (INF-P1–P4) — guarded
  cells plug into the same INF-A1 lowering;
- no serialization of splits into the parity surface before the producer lands
  (the INF-R2 discipline, applied to the new axis).

## 10. Where this runs, and when

Per P-036's authority table: nothing here may be implemented in Python (a
moving parity target) or in Rust (a deliberate divergence) before the P-022
cutover. The implementation home is the post-cutover summary engine (#304),
with the derivation half naturally expressed over OwnCFG cells and the
application half in the same lowering seam INF-A occupies today. The #305
lexical predicates remain the extractor-side floor until then; when this layer
lands, they become redundant witnesses the corpus keeps as regression anchors.

Acceptance for this proposal (design review, no code):

- the fixed-split-before-solve decision (G-L1) and its associativity rationale;
- the five-transform edge vocabulary (G-S5/G-F2) as the entire guard
  propagation story;
- G-T1/G-T2 accepted as the proof obligations the implementation PR must
  discharge with tests (fixture families of §8);
- the walls of §9 accepted as walls.
