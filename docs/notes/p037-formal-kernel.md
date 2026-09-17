# P-037 formal kernel — the A0 spike (Kani now, Verus maybe)

> Status: **A0 spike complete; kernel kept** (kill criterion evaluated in §6).
> Crate: [`formal/p037-kernel/`](../../formal/p037-kernel/). Not a P-037
> implementation (P-037 §10 keeps that post-cutover), not a member of the
> `rust/` workspace (P-022's crate graph is the architecture), wired to
> nothing, changes no verdict. Follows the SHRINK hand-off of
> [`p036-bakeoff.md`](p036-bakeoff.md) §8.5: vertical A begins with a checked
> kernel, and A1 reuses these functions instead of writing a second copy.
>
> Evidence discipline as in the bakeoff note: `REPOSITORY FACT`,
> `MEASURED OBSERVATION` (a checker ran here; its log is quoted),
> `INFERENCE`, `PROPOSED` (P-037 text), `OWNER RULING`.

## 1. What was asked (OWNER RULING, condensed)

Two levels, started small. **Kani now**: extract the pure P-037 kernel
(Transfer, Election, guarded cells, joins, collapse, finalize, the five edge
transforms, application) without Roslyn / files / SARIF, and write harnesses
K1–K10 — lattice laws, monotonicity of every transform and of the election
import (Conflict included), collapse monotone, the G-A2 floor, no fabricated
consume, `id`/`neg` involutions, the residual-⊥ cases *first*, and
order-independence of the concrete solver on small symbolic SCCs. **Verus
later**, only for G-T2 (`C(fin(lfp F_G)) ≤ fin(lfp F_0)`) and the solver's
monotone order-independent lfp, and only if the kernel stays a compact pure
theorem. Do **not** start from G-T1 whole (it drags in Roslyn → CFG → guard
eligibility → G-V4 aliasing). Trusted-input boundary: guard eligibility and
cell-local definite-release facts are assumed correct; verify from election,
cells, solver, transforms, collapse, finalize, application. Do **not** write a
separate "verifier model" and then a production implementation: the checked
functions *are* the kernel. Kill criterion: stop if Kani needs half of
Roslyn/CFG modelled; keep if the pure kernel is a few hundred LOC and the
harnesses stay local.

## 2. What was built (REPOSITORY FACT)

`formal/p037-kernel/src/lib.rs` — one file, 497 code lines (731 with docs):

| P-037 rule | kernel item |
|---|---|
| INF-L1/L2 base lattice | `Transfer { Bot, No, Must, May, Unknown }`, `join`, `leq`, `fin` |
| G-L2 product cells, G-T2 collapse, G-L4 | `Cells { pos, neg }`, cellwise `join`/`fin`, `collapse = join(pos, neg)`, `diag`, `swap` |
| G-S1 flat election lattice + stage-2 import | `Election { None, One(g), Conflict }`, `join`, `import(callee, GuardBinding)`, `shape_of` |
| G-S5 / G-F2 five transforms, G-S4 branch mask | `Transform { ConstPos, ConstNeg, Id, Neg, Opaque }`, `read`, `Mask { Both, PosOnly, NegOnly }`, `contribute` |
| G-F1 one SCC, `F_G` | `System { n, coords: [Coord { shape, seed, edges }; 3] }`, `well_formed`, `step` |
| G-T2 §7.2's `F_0` | `System::collapsed()` — every coordinate `Uncond`, seeds collapsed, every edge `Opaque`/`Both` |
| today's `_build_skeletons` ladder | `System::today()` — release priority (definite ⇒ `dispose`, partial ⇒ `[dispose, borrow]`, forwards dropped), else forwards + synthetic `borrow` on conditional / multi-target handoffs (`ownlang/ownir.py`, the `if rel:` / `elif passed:` ladder, REPOSITORY FACT) |
| INF-F3 solver | `lfp_jacobi`, `lfp_chaotic(schedule)` over a `Lattice` trait, bounded by `MAX_COORDS × HEIGHT + 1` passes; `solve`, `solve_with`, `elect`, `elect_with` |
| G-A1 / G-A2 / G-A3 / G-A5 | `Selection`, `Lowered { Consume, Borrow, Plain }`, `lower` (finalizes first), `apply` |
| G-T2 §7.3 residual-⊥ lemma | `Grounding { PartialLocalRelease(t), GroundedForward(t), Ungrounded }`, `lemma_guarded`, `lemma_today` |

Bounds: 3 coordinates, 2 edges per coordinate, guards as `u8`. The `rust/`
workspace's strict lints are copied verbatim (`unsafe` forbidden, no
indexing, no unchecked arithmetic, no `unwrap`, no `panic`); `cargo clippy
--all-targets` is clean.

`src/properties/` — 1 395 code lines: every property twice over the same
functions, a `#[kani::proof]` harness and a `#[test]` twin (exhaustive over
the finite domains — all 5 transfers, 25 cell pairs, 5 elections, 20
bindings, every well-formed system of ≤ 2 coordinates with ≤ 1 edge each —
and 20 000 seeded-random systems of 3 coordinates with ≤ 2 edges where
exhaustion is out of reach).

## 3. Results (MEASURED OBSERVATIONS)

`cargo test`: **35 passed, 0 failed** (≈ 19 s, `opt-level = 2` test
profile). `cargo kani` (Kani 0.68.0, CBMC 6.11.0, pinned nightly
2026-08-21): see the table.

| # | property (P-037 rule) | test twin | Kani harness | Kani bound |
|---|---|---|---|---|
| K1 | `Transfer` join commutative / associative / idempotent, `⊥` identity, `unknown` absorbing; `leq` a partial order with `no`/`must` incomparable; `Cells` inherit componentwise (G-L2/G-L3) | exhaustive | running at this checkpoint | all values |
| K2 | `Election` join laws, `None` identity, `Conflict` absorbing, `One(g)`/`One(h)` incomparable (G-S1) | exhaustive | running at this checkpoint | all values |
| K3 | every `read(τ, ·)` and `contribute(m, ·)` monotone; every read component ≤ the collapse (the §7.2 lemma) (G-F2/G-S4) | exhaustive | running at this checkpoint | all values |
| K4 | `import` monotone, `Conflict → Conflict`, `None → None`; maps exactly the bound guard; is **not** a join-morphism (pinned, only monotonicity is claimed) (G-S1) | exhaustive | running at this checkpoint | all values |
| K5 | `collapse` monotone and a join-morphism; `C(Uncond(t)) = t` (G-T2) | exhaustive | running at this checkpoint | all values |
| K6 | `apply` yields `consume` iff a selected finalized `must` cell or a unanimous finalized `must`; a selected `no` cell is `borrow` (G-A2/G-A3); `Uncond` ignores selection | exhaustive | SUCCESSFUL | all values |
| K7 | unselected differing cells never consume; a selected `unknown` cell is `plain`; an opaque read of finalized cells consumes only when both are `must`; raw `⊥` lowers to `borrow`; **the unfinalized witness** `(must, ⊥)` reads as `must` inside the solver and `apply` therefore finalizes first (§4 F2) | exhaustive + pin | SUCCESSFUL | all values |
| K8 | `read(id, read(id, c)) = c`, `read(neg, read(neg, c)) = c`; `const-pos`/`const-neg`/`opaque` reads are diagonal (G-F2) | exhaustive | running at this checkpoint | all values |
| K9 | residual-⊥ lemma: `C(fin(other, ⊥)) ≤ fin(today)` for all three groundings and every `other`; the §7.3 non-commutation witness `C(fin(must, ⊥)) = may ≠ fin(C(must, ⊥)) = must` (G-T2.3) | exhaustive + pin | running at this checkpoint | all values |
| K10 | the solver stabilizes within the height bound; its result is a fixpoint, the **least** fixpoint (checked against every fixpoint of the domain), and equal under every permutation schedule and a repeating fair schedule; the election pre-solver likewise; §8 row 11 (late `Conflict` cannot leave a stale import) (G-F1/G-F2, G-S1) | exhaustive n ≤ 2 + 20 000 random n = 3 | KANI_K10 / KANI_K10E | n ≤ 3, ≤ 2 edges, any permutation |
| K11 | G-T2 §7.2 lax simulation against the **collapsed** system: one step `C(F_G(X)) ≤ F_0(C(X))` for every state, and at the lfp `C(lfp F_G) ≤ lfp F_0` — unconditional | exhaustive + 20 000 random | KANI_K11S / KANI_K11 | n ≤ 3, ≤ 2 edges |
| K11′ | G-T2 as stated, against **today's derivation** post-finalization: `C(fin(lfp F_G)) ≤ fin(lfp F_0)` — holds under two trusted-input assumptions (release cells carry no edges; no `unknown` seed in the SCC) and **fails without the second** (§4 F1, pinned) | exhaustive + 20 000 random + counterexample pin | running at this checkpoint | n ≤ 3, ≤ 2 edges |
| K12 | `Uncond` coordinates stay diagonal through the solver (justifies the pair representation of §3) | exhaustive + random | running at this checkpoint | n ≤ 3 |
| K13 | P-037 §8 rows 1, 3, 7, 8, 9, 12, 13, 14, 16, 17, 18 as concrete pins, each with today's value where the row states one | pins | — | — |

## 4. Findings (the point of the exercise)

- **F1 — G-T2's `≤` is not true against today's actual derivation
  (INFERENCE from a REPOSITORY FACT, pinned by
  `k11_finding_release_priority_drops_an_unresolved_forward`).** P-037 §7.1
  states that today's release branch has priority and "the forward is never
  processed"; `ownlang/ownir.py` does exactly that (`if rel:` wins over
  `elif passed:`). §7.2 then argues `C(F_G(X)) ≤ F_0(C(X))` with `F_0` as
  the *collapsed read* — but the collapsed read is not today. For
  `if (g) p.Dispose(); else Extern(p);` with `Extern` unresolved, the guarded
  cells are `(must, unknown)`, collapse `unknown`; today drops the forward
  and says `may`. `unknown ≰ may`: the lax refinement fails, pre- and
  post-finalization. The only way today can be *smaller* than the collapse is
  this dropped edge, and the only value that makes it bite is `unknown`
  (`must`, `may`, `no`, `⊥` sinks all keep `≤`, K11′ proves it). The verdict
  class is unaffected — INF-A1 lowers `may` and `unknown` alike to `plain` +
  OWN051 — so this is a defect in the *statement* of G-T2, not a soundness
  hole. Options for the contract, none taken here: (a) state G-T2 modulo
  INF-A1's lowering (`may ≡ unknown` at application); (b) keep the value-level
  claim and add the hypothesis "no unresolved callee reaches a
  release-priority coordinate"; (c) accept `unknown` as the honest answer and
  retire the §7.1 sentence "today says `may`" as a claim of *refinement* for
  that shape (today is optimistic there, not conservative).
- **F2 — application must finalize before it collapses or selects, and the
  order is load-bearing.** The first version of the K7 twin lowered an opaque
  read of *unfinalized* cells and failed: inside the solver `⊥` is the join
  identity (INF-L2), so `(must, ⊥)` reads as `must`, while the finalized pair
  `(must, no)` collapses to `may`. G-A2's word "finalized" is the whole
  difference between an honest `plain` and a fabricated `consume`. The kernel's
  `apply` finalizes first; the witness is pinned so an A1 that applies a raw
  solver value fails a test, not a user.
- **F3 — the election import is monotone but not a join-morphism** (pinned in
  `k4_import_is_monotone_and_conflict_propagates`): `One(h) ⊔ One(h')`
  imports as `Conflict` while the two imports join to `One(g)` or `None`. G-S1
  claims only monotonicity, which is what the lfp needs; an optimizer that
  distributes imports over joins would be wrong.
- **F4 — the pure-lattice half of G-T2 is machine-checked** (K11): every
  transform read sits below the collapse, masking only lowers, `C` is a join
  morphism, so `C(F_G(X)) ≤ F_0(C(X))` for every state and every bounded SCC,
  and the lfps inherit it. This is the induction P-037 §7.2 sketches, run by
  a model checker for n ≤ 3 instead of by hand for one case.
- **F5 — the residual-⊥ lemma holds in all three branches for every cell
  value** (K9), not only for the three representatives of §8 rows 14/16 and
  the pure-ungrounded fixture; and the non-commutation witness is pinned.
- **No counterexample to K1–K10 as the owner listed them.** The two design
  findings are both in G-T2's *statement* (F1) and in what "finalized" means
  at application (F2); the algebra itself did what P-037 says it does.

## 5. Trusted-input boundary, restated as obligations for A1

`System.well_formed()` plus two lemma-side assumptions encode what the
frontend must guarantee and the kernel cannot check:

1. an `Uncond` coordinate has a diagonal seed, `Both` masks, no `id`/`neg`
   edge; an `id`/`neg` edge joins two `Split` coordinates whose split
   variables correspond through that argument and are entry-value stable
   (G-V4 — *the* soundness precondition, outside this kernel);
2. cell-local facts are consistent: a cell recording a local release carries
   no forward edge (`release_cells_have_no_edges`);
3. for G-T2 as a value-level claim: no unresolved callee inside the SCC
   (`no_unknown_seed`) — or restate G-T2 per F1.

Each is a fixture-family obligation for the implementation PR (P-037 §8's
discharge matrix already lists the G-V4 negative controls).

## 6. Kill criterion (OWNER RULING, applied)

- "If Kani requires modelling half of Roslyn/CFG, STOP." It did not: the
  harnesses model nothing outside the algebra; the one derivation-side rule
  that had to be represented (today's release-priority ladder) is six lines
  and was needed only to check the theorem P-037 itself states against
  today. **Not triggered.**
- "If the pure semantic kernel ≤ roughly a few hundred LOC and the proof
  harnesses stay local, KEEP." Kernel 497 code lines including both "today"
  models and the election pre-solver; harnesses are per-property, in one
  crate, and run in ≈ 19 s (`cargo test`) / a time to be recorded when the run completes (`cargo kani`).
  **Keep.**

## 7. What A1 and A2 inherit

- **A1 (P-037 implementation, first target the may-as-must `ConsumesParam`
  hole).** Move `formal/p037-kernel/src/lib.rs` into the post-cutover summary
  engine as-is; the twins go with it and keep running under `cargo test`;
  `cargo kani` stays an opt-in job until it has a CI budget. Application must
  call `fin` before selecting or collapsing (F2). The G-T2 claim the
  implementation discharges with tests must be the one that is true (F1).
- **A2 (Verus, optional).** The candidate theorem is exactly K11's lfp form
  generalized past the bound: `∀ S well-formed: C(lfp F_G(S)) ≤ lfp F_0(C(S))`,
  by induction over iterations with K11's one-step lemma — a compact
  statement over `Lattice` and `System::step`, no allocation, no `unsafe`,
  finite domains. Verus-shaped. G-T2 *as stated post-finalization* needs
  F1 resolved first, or the `no_unknown_seed` hypothesis carried into the
  statement.
- **Not inherited:** any claim about G-T1 as a whole. The precision floor
  from honest facts is K6/K7; the honesty of the facts is Roslyn/CFG/G-V4
  territory and stays in the fixture matrix.
