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
applies today's lowering rule to the collapsed value. Collapse never coarsens
the summary (a proven lax refinement, §7 — on mixed release/forward bodies it
is strictly *more* precise than today, a declared verdict-change class), so
the layer degrades to the current behavior everywhere the guard vocabulary
does not apply — and the flagship `Teardown(bool)` / null-guard-helper cases
stop falling through the architecture.

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

### The shape — election first, then a fixed domain

The type is deliberately **not** a runtime sum the solver could reshape
mid-flight. Election is a separate, pre-solver artifact, and it *types* the
coordinate:

```text
Election(M, i) ::= None | One(g) | Conflict        -- fixed before the solver (G-S1)

D(M, i) = Transfer                     when Election(M, i) ∈ {None, Conflict}
D(M, i) = Transfer × Transfer          when Election(M, i) = One(g)

    t ∈ Transfer = {⊥, no, must, may, unknown}     (INF-L1/L2)
    g = a guard variable of this method (G-V1)
```

For an elected coordinate, `(t_pos, t_neg)` are the transfers when `g`'s
positive side holds (`p == true` / `q != null`) and its negative side,
respectively. After election the domain of a coordinate is **immutable**:
no value changes shape during the solve. `Uncond(t) ≡ (t, t)` is a
**read-only diagonal embedding** used when a `Transfer`-typed neighbour is
read from an elected coordinate's edge — never a way to convert a stored
value.

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

- **G-S1 (split election — its own monotone fixpoint, pre-solver).**
  Election is computed in the three-point **election lattice**, not as a bare
  candidate set (a singleton-set import operator is *not monotone*: a callee's
  candidate set growing `{a} ⊂ {a, b}` would flip an importer from `{x}` to
  `∅`, shrinking the output as the input grows — order dependence through the
  back door, before the value solver even starts):

  ```text
  Election ::= None | One(g) | Conflict          -- height 2, finite

  None      ⊔ x         = x
  One(g)    ⊔ One(g)    = One(g)
  One(g)    ⊔ One(h)    = Conflict      (g ≠ h)
  Conflict  ⊔ x         = Conflict
  ```

  *Stage 1 (own body, the seed):* for each guard literal (G-V1) lexically
  governing an ownership action on parameter `i` — an enclosing single-literal
  `if`/`else`, or a single-literal-guarded early `return` preceding the action
  (the two shapes #305 pinned) — contribute `One(g)`. The seed of `(M, i)` is
  the election-lattice join of these contributions (so zero literals seed
  `None`, and two distinct variables seed `Conflict` directly). The candidate
  space is bounded by `|GuardVars(M)|` per `(M, resource parameter)` — finite,
  and **not** "at most one": the lattice, not a cardinality assumption, is
  what makes the fixpoint well-defined.
  *Stage 2 (import along edges):* an import is licensed only by the
  **conjunction of two facts on the same call**:

  ```text
  resource edge:   caller (M, resource param i) -> callee (C, resource param k)
  guard binding:   callee guard param h := g | !g | constant | opaque
                   (the argument bound to h at that same call)
  ```

  The import of `Election(C, k)` into `(M, i)` through that call is the map:
  `None → None`; `One(h) → One(g)` when `h` is exactly the guard parameter
  bound from the caller's `g` by an `id`/`neg` binding; `One(h') → None` for
  any other variable; `Conflict → Conflict` (conservative: a conflicted
  callee poisons its election-bearing importers rather than silently
  dropping out). This map is monotone on the election lattice, imports are
  joined with the seed, and the whole election assignment is the **least
  fixpoint** of a monotone operator on a finite lattice — deterministic and
  order-independent by construction, completed strictly before the value
  solver, so G-L1 holds. This is what lets a wrapper that merely *forwards*
  its flag (worked cases 7–8) inherit the split, its own body having no
  literal to elect from.
  Then, per `(method, parameter)`: `One(g)` → the coordinate is
  `Split` over `g`; `None` / `Conflict` → `Uncond`, derived as today
  (both-cell semantics; the honest join). The `Conflict`-propagation rule
  knowingly trades wrapper precision for determinism — a provenance-aware
  per-edge refinement is possible later, behind the same lattice, and is a
  recorded non-goal today (§9).
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
- **G-A2 (the floor, restated for cells).** A `consume` may be applied in
  exactly two situations:
  1. **selected must** — a cell whose finalized value is `must`, selected by
     G-A1's static test at *this* call site; or
  2. **unanimous must** — no selection, but the finalized summary's collapse
     is `must`, i.e. *every* cell is `must`: both sides of the guard provably
     consume, so knowing the guard is unnecessary (this is also what makes an
     `Uncond(must)` reached through a `const-pos`/`const-neg` edge lower as
     it always has).
  Nothing else: no cross-call-site inference, no "most callers pass true", no
  default cell. An unselected `Split` whose cells *differ* never applies a
  cell alone — it lowers the collapse (G-A1).
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
  was `must`); and `must` is *applied* only under G-A2 — a statically selected
  `must` cell, or a unanimous summary whose every cell is `must` (the guard
  provably irrelevant). Both application routes rest on the same cell-definite
  evidence; neither invents a cell. Every non-vocabulary shape, laundered
  guard, conflicted election, opaque transform, or unknown argument over
  *differing* cells lands on a join — never a guess. The floor (`own-only 0`,
  INF §"The floor") is preserved verbatim.
- **G-T2 (refinement — a `≤`, deliberately not an `=`).** Define
  `C(Uncond(t)) = t`, `C(Split(g, a, b)) = join(a, b)` (collapse), and
  `fin` = the cellwise `⊥ → no` finalization (G-L4 / INF-L2). The claim is a
  **lax simulation**, not equality — equality is *false*, and knowably so:

  1. **Why not equality (the mixed release/forward counterexample).**
     `void M(Resource p, bool g) { if (g) p.Dispose(); else Sink(p); }` with
     `Sink` an unconditional consumer. Guarded derivation:
     `pos = must` (local release), `neg = must` (forward resolved through
     `Sink`), collapse `must`. Today's `_build_skeletons` is not an ideal
     path-join: the release branch has *priority* — any partial local release
     emits `[dispose, borrow]` and the forward is never processed — so
     today's value is `may`. `collapse(guarded) = must ≠ may = today`, and
     `must` is the *refinement* (`must ≤ may` in the precision order). The
     guarded layer separates release-paths from forward-paths where today's
     derivation flattens them: this is a **second, declared class of Phase-2
     verdict changes** (beyond G-A1 selection) and enters the conformance
     matrix as such (§8 row 12). "Unknown guard behaves byte-for-byte like
     today" is therefore also too strong and is *not* claimed: what holds is
     that the same INF-A1 lowering rule is applied to the collapsed value —
     the value itself may be strictly more precise.
  2. **Solver lax simulation (pre-finalization).** `C` is a join-morphism on
     the product lattice
     (`C((a,b) ⊔ (c,d)) = (a⊔c) ⊔ (b⊔d) = C(a,b) ⊔ C(c,d)`), and every G-F2
     edge read laxly commutes with it: a projected, swapped, or mapped cell is
     `≤` the join of cells, so `C(F_G(X)) ≤ F_0(C(X))` pointwise, where `F_G`
     is the guarded global transfer function and `F_0` today's. By induction
     over iterations, `C(F_G^n(⊥)) ≤ F_0^n(⊥)`, and both chains stabilize
     (finite height), hence `C(lfp F_G) ≤ lfp F_0`.
  3. **Finalization does not commute — and must be argued, not waved at.**
     `C(fin(must, ⊥)) = C(must, no) = may`, while
     `fin(C(must, ⊥)) = fin(must) = must`: finalization can *raise* the
     collapse. A one-cell residual `⊥` is reachable
     (`F(p, g) { if (g) p.Dispose(); else F(p, g); }` — the negative cell
     reads only its own ungrounded same-SCC edge and stays `⊥` at the lfp).
     The theorem is therefore stated **post-finalization**:
     `C(fin(lfp F_G)) ≤ fin(lfp F_0)`, with two supporting definitions and a
     case lemma:
     - *cell semantics:* cell definiteness quantifies over the cell's
       **normal-return paths**, exactly as INF-S2 quantifies globally; a cell
       with no normal-return path contributes vacuously (matching the base
       layer's treatment of never-returning paths);
     - *residual-⊥ lemma:* a cell is `⊥` at the lfp only when its every
       contribution is an ungrounded same-SCC forward. In every such skeleton
       shape today's derivation is already `≥ may` (a partial local release on
       the other side triggers the `[dispose, borrow]` priority) or is itself
       residual-`⊥` (the pure-forward case, where both sides finalize `no`
       identically) — so finalizing the guarded cell to `no` never lifts the
       collapse above today's value. This lemma is a **proof obligation the
       implementation must pin with tests** (§8 row 14), not a formality: it
       is exactly where a future derivation change could silently break the
       refinement.
  4. **Application compatibility (weakened accordingly).** With no static
     selection, G-A1 applies today's *lowering rule* to `C(fin(summary))`;
     the resulting verdict coincides with today's wherever the value does
     (all `None`-election coordinates, all vocabulary-free bodies) and is
     more precise exactly in the two declared classes (selection, and the
     release/forward separation of point 1).
  Consequence for migration: the summary dump gains the election and the
  cells as additive fields plus a derived collapsed view; diffing the
  collapsed view against today's golden dumps isolates exactly the two
  declared Phase-2 verdict-change classes, and nothing else.

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
| 9 | alternating recursion `F(p, bool g){ if (g) release p; else F(p, !g); }` | least fixpoint `Split(g, must, must)` = collapse `must` — correct: every execution releases. (Under a synchronous Jacobi update this stabilizes in two sweeps: pos `must` from the local release, then neg `must` through the `neg` edge. The sweep count is an illustration of one schedule; the lfp itself is schedule-independent by G-F2's monotonicity — the scheduler is not part of the mathematics.) | any | `consume` (G-A2 case 2: unanimous `must`) |
| 10 | disagreeing call sites `Teardown(true)` + `Teardown(false)` in one program | one summary, per-site selection (G-A1) — no cross-site contamination; each site gets its own row-1 verdict | — | — |
| 11 | **late election conflict:** wrapper `W(bool f){ Inner(f); }`; `Inner`'s election grows `One(a)` → `Conflict` (a second guarded action over `b` appears in `Inner`) | the election fixpoint re-runs on the new skeleton set: `Conflict` imports as `Conflict` (G-S1), so `W` collapses to `Uncond` — a stale imported `One(a)` cannot survive, because election is a least fixpoint of a monotone operator, not an add-only set | any | today's behavior |
| 12 | **mixed release/forward:** `if (g) release p; else MustSink(p);` | `Split(g, must, must)`, collapse `must` — where today's rel-priority derivation says `may` (G-T2.1's counterexample; the second declared verdict-change class) | any (no selection needed) | `consume` (G-A2 case 2) |
| 13 | **unknown call site over unanimous cells:** row-12 summary, `M(p, x)` with `x` unknown | no selection, but `C(fin) = must` | — | `consume` — selection is unnecessary when both sides consume |
| 14 | **one-cell residual ⊥:** `F(p, g){ if (g) release p; else F(p, g); }` (same-guard recursion, no grounding) | lfp `(must, ⊥)` → `fin` → `(must, no)` → collapse `may`; today: partial release ⇒ `may`. Equal — the residual-⊥ lemma's pin (G-T2.3) | unknown site | plain + OWN051 (today); `F(p, true)` selects `must` → `consume`; `F(p, false)` selects `no` → `borrow` → honest OWN001 |
| 15 | **overload/election ordering:** sig-keyed summary (roadmap stage 2) elects `Split`; the name-merged fallback group contains a differing election | G-F3: the merge collapses every side to `Uncond` first, then joins — deterministic, pre-solver; the precise `sig`-keyed summary keeps its split where the call carries a `sig` | `sig`-resolved site | per-cell verdicts; name-fallback site: today's behavior |

Each row is a fixture family for #304's conformance vectors; rows 1–3 are the
summary-level twins of the corpus cases #305 landed, and must agree with them;
rows 11–15 pin the election lattice, both G-T2 refinement classes, and the
finalization lemma.

## 9. Non-goals (walls, not TODOs)

- no conjunctions/disjunctions or multi-variable predicates (G-V2);
- no field/local/property guards, no guard state threading (G-V3);
- no guard propagation beyond the single-edge transforms of G-S5 — in
  particular no caller-of-caller constant folding;
- no provenance-aware election: a `Conflict` poisons its election-bearing
  importers wholesale (G-S1); recovering wrapper precision through per-edge
  provenance is a possible later refinement *behind the same lattice*, not
  part of this contract;
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

- the fixed-split-before-solve decision (G-L1) and its associativity
  rationale, with election typed as its own three-point lattice
  (`None`/`One(g)`/`Conflict`) solved by a monotone pre-solver fixpoint
  (G-S1) — never a candidate set with a singleton filter;
- the five-transform edge vocabulary (G-S5/G-F2) as the entire guard
  propagation story;
- G-A2's two consume routes (selected `must`; unanimous `must`) as the
  application floor;
- G-T1/G-T2 accepted as the proof obligations the implementation PR must
  discharge with tests (fixture families of §8) — G-T2 explicitly as a lax
  refinement (`≤`) post-finalization, with the residual-⊥ lemma pinned, never
  as derivation equality;
- both declared verdict-change classes (cell selection; release/forward
  separation) entered into the #304 conformance matrix;
- the walls of §9 accepted as walls.
