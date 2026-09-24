# P-037 formal kernel — the A0 spike (Kani now, Verus maybe)

> Status: **A0 spike complete, terminal at `9523fac` — PASS / KEEP (OWNER
> RULING, §8); A0.5 (the G-T2 correction) done in the same branch.** Kill
> criterion evaluated in §6.
> Crate: [`formal/p037-kernel/`](../../formal/p037-kernel/). Not a P-037
> implementation (P-037 §10 keeps that post-cutover), not a member of the
> `rust/` workspace (P-022's crate graph is the architecture), wired to
> nothing, changes no verdict. Follows the SHRINK hand-off of
> `p036-bakeoff.md` §8.5 (branch `claude/p036-capability-bakeoff-fzw74t` at
> `ce2e6bc`; not in this tree — §9): vertical A begins with a checked
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

`src/properties/` — every property twice over the same functions, a
`#[kani::proof]` harness (22 of them) and a `#[test]` twin (35; exhaustive
over the finite domains — all 5 transfers, 25 cell pairs, 5 elections, 20
bindings, every well-formed system of ≤ 2 coordinates with ≤ 1 edge each —
and 20 000 seeded-random systems of 3 coordinates with ≤ 2 edges where
exhaustion is out of reach).

Harness engineering that turned out to matter (MEASURED OBSERVATION): the
first whole-solver harness — a symbolic 3-coordinate SCC with a symbolic
live count, `usize` indices and the kernel's iterator-adapter loops — ran
CBMC's symbolic execution for 472 s, produced a 2.4-million-step program
and **ran out of memory** in the SAT phase on a 16 GB host, for the
*election* solver, the small one. Five changes made every harness
tractable without touching what is proven — each one measured, because
the first three were not enough: (1) the harnesses draw `u8` symbols and
convert (`properties::symbolic`); (2) the live-coordinate count is concrete
(3, or 2 for the "small" systems); (3) the kernel's `step` / Jacobi /
`well_formed` loops are plain loops instead of `flatten`/`fold`/`enumerate`
chains; (4) a coordinate looked up at a *symbolic* index is **copied out of
the array** instead of borrowed — a reference at a symbolic index is a
symbolic-offset pointer for CBMC and every field read through it is a case
split: the one-step election harness went from unfinished at 7 min / 1.5 GB
to proven in 3.9 s on this change alone; (5) `collapsed()` / `today()` are
by-value `array::map` transforms instead of `iter_mut().flatten()` updates
through mutable references: the G-T2 one-step harness went from unfinished
at 16 min / 1.7 GB to proven in 8.9 s. Semantics unchanged throughout: the
35 twins are the witnesses, run after every change. The whole-solver
properties are then checked in two forms: the *inductive*
one-step lemma on a symbolic 3-coordinate SCC and a symbolic state (`step`
monotone; F_G keeps `Uncond` diagonal; the §7.2 one-step inequality), plus
the *direct* whole-solver statement on 2-coordinate SCCs with ≤ 1 edge each
(chaotic = Jacobi under every fair schedule; the lfp inequalities). Order
independence of the lfp follows from the inductive facts by the standard
argument (a monotone operator on a finite lattice: every fair chaotic
iteration from `⊥` reaches the least fixpoint); the direct harness is the
model checker looking at the concrete solver as well.

## 3. Results (MEASURED OBSERVATIONS)

`cargo test`: **35 passed, 0 failed** (≈ 19 s, `opt-level = 2` test
profile). `cargo kani` (Kani 0.68.0, CBMC 6.11.0, pinned nightly
2026-08-21, one harness at a time on a 4-core / 16 GB container):
**22 of 22 harnesses SUCCESSFUL**, per-harness wall times in the table;
the two heaviest are the cells solver's least-fixpoint harness at the full
3-coordinate / 2-edge bound (5.0 min) and chaotic = Jacobi on small SCCs
(4.0 min); everything value-level is under a second.

| # | property (P-037 rule) | test twin | Kani harness | Kani bound |
|---|---|---|---|---|
| K1 | `Transfer` join commutative / associative / idempotent, `⊥` identity, `unknown` absorbing; `leq` a partial order with `no`/`must` incomparable; `Cells` inherit componentwise (G-L2/G-L3) | exhaustive | SUCCESSFUL (1.8 s, 3 harnesses) | all values |
| K2 | `Election` join laws, `None` identity, `Conflict` absorbing, `One(g)`/`One(h)` incomparable (G-S1) | exhaustive | SUCCESSFUL (0.6 s) | all values |
| K3 | every `read(τ, ·)` and `contribute(m, ·)` monotone; every read component ≤ the collapse (the §7.2 lemma) (G-F2/G-S4) | exhaustive | SUCCESSFUL (0.8 s) | all values |
| K4 | `import` monotone, `Conflict → Conflict`, `None → None`; maps exactly the bound guard; is **not** a join-morphism (pinned, only monotonicity is claimed) (G-S1) | exhaustive | SUCCESSFUL (0.6 s) | all values |
| K5 | `collapse` monotone and a join-morphism; `C(Uncond(t)) = t` (G-T2) | exhaustive | SUCCESSFUL (0.6 s) | all values |
| K6 | `apply` yields `consume` iff a selected finalized `must` cell or a unanimous finalized `must`; a selected `no` cell is `borrow` (G-A2/G-A3); `Uncond` ignores selection | exhaustive | SUCCESSFUL (0.6 s) | all values |
| K7 | unselected differing cells never consume; a selected `unknown` cell is `plain`; an opaque read of finalized cells consumes only when both are `must`; raw `⊥` lowers to `borrow`; **the unfinalized witness** `(must, ⊥)` reads as `must` inside the solver and `apply` therefore finalizes first (§4 F2) | exhaustive + pin | SUCCESSFUL (0.6 s) | all values |
| K8 | `read(id, read(id, c)) = c`, `read(neg, read(neg, c)) = c`; `const-pos`/`const-neg`/`opaque` reads are diagonal (G-F2) | exhaustive | SUCCESSFUL (0.6 s) | all values |
| K9 | residual-⊥ lemma: `C(fin(other, ⊥)) ≤ fin(today)` for all three groundings and every `other`; the §7.3 non-commutation witness `C(fin(must, ⊥)) = may ≠ fin(C(must, ⊥)) = must` (G-T2.3) | exhaustive + pin | SUCCESSFUL (0.6 s) | all values |
| K10 | the solver stabilizes within the height bound; its result is a fixpoint, the **least** fixpoint (test: against every fixpoint of the domain; Kani: against every symbolic fixpoint), and equal under every permutation schedule and a repeating fair schedule; §8 row 11 (late `Conflict` cannot leave a stale import) (G-F1/G-F2) | exhaustive n ≤ 2 + 20 000 random n = 3 | K10a `step` monotone in the state: SUCCESSFUL (6.3 s) · K10b `solve` is a fixpoint below every fixpoint: SUCCESSFUL (300 s) · K10c chaotic = Jacobi: SUCCESSFUL (240 s) | K10a/b: n = 3, ≤ 2 edges, symbolic state; K10c: n = 2, ≤ 1 edge, any fair schedule |
| K10e | the election pre-solver: the same three facts (G-S1) | exhaustive twins of K10 | step monotone: SUCCESSFUL (3.9 s) · least fixpoint: SUCCESSFUL (24 s) · chaotic = Jacobi: SUCCESSFUL (44 s) | as K10 |
| K11 | G-T2 §7.2 lax simulation against the **collapsed** system: one step `C(F_G(X)) ≤ F_0(C(X))` for every state, and at the lfp `C(lfp F_G) ≤ lfp F_0` — unconditional | exhaustive + 20 000 random | one step: SUCCESSFUL (8.9 s) · lfp: SUCCESSFUL (73 s) | one step: n = 3, ≤ 2 edges, symbolic state; lfp: n = 2, ≤ 1 edge |
| K11′ | G-T2 *as originally stated*, against **today's derivation** post-finalization: `C(fin(lfp F_G)) ≤ fin(lfp F_0)` — holds under two trusted-input assumptions (release cells carry no edges; no `unknown` seed in the SCC) and **fails without the second** (§4 F1, pinned). **K11b — G-T2b as amended (A0.5):** with consistent cell facts only, `C(fin(lfp F_G)) ≤ fin(lfp F_legacy)` **or** the pair is exactly (`unknown`, `may`), the declared class 3; plus the row-14 pin that the bare collapsed system is *not* a post-finalization bound | exhaustive + 20 000 random + counterexample pin; K11b exhaustive + 20 000 random | SUCCESSFUL (79 s) · K11b: SUCCESSFUL (100 s) | n = 2, ≤ 1 edge |
| K12 | `Uncond` coordinates stay diagonal through the solver (justifies the pair representation of §3) | exhaustive + random | one step keeps them diagonal: SUCCESSFUL (5.3 s) · lfp: SUCCESSFUL (26 s) | one step: n = 3; lfp: n = 2, ≤ 1 edge |
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
  **Resolution (A0.5, OWNER RULING — (a) + (c), explicitly not (b)):** P-037
  §7 now states **G-T2a**, the algebraic collapse refinement against the
  collapsed semantic system `F_C`, pre-finalization (`C(F_G(X)) ≤ F_C(C(X))`,
  hence `C(lfp F_G) ≤ lfp F_C` — K11), with §8 row 14 recorded as the witness
  that the bare `F_C` is *not* a post-finalization bound (pinned:
  `row14_bare_collapsed_baseline_is_not_a_post_finalization_bound`); and
  **G-T2b**, observational compatibility with today's derivation at the
  INF-A1 lowering, within three declared classes — application refinement,
  summary refinement, and the new **class 3, legacy-honesty difference**
  (guarded `unknown` for today's `may`, verdict-equivalent, and never
  allowed to change a verdict without a separate declared class). The
  value-level residue that survives is the disjunction the kernel now checks
  with no `no_unknown_seed` hypothesis (K11b, exhaustive + random + Kani on
  small SCCs): guarded `≤` legacy **or** exactly (`unknown`, `may`). The
  migration consequence in P-037 lists the three classes and forbids a
  fourth by fiat. The residual-⊥ lemma stays as the finalization half of
  G-T2b, all three branches pinned.
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
  crate, and run in ≈ 19 s (`cargo test`) / 13.6 min for all 22 harnesses, sequential, one CBMC at a time (`cargo kani`).
  **Keep.**

## 7. What A1 and A2 inherit

- **A1 (P-037 implementation, first target the may-as-must `ConsumesParam`
  hole).** Move `formal/p037-kernel/src/lib.rs` into the post-cutover summary
  engine as-is; the twins go with it and keep running under `cargo test`;
  `cargo kani` runs the fast harnesses on every push and the whole-solver
  ones nightly (§8, CI split). Application must call `fin` before selecting
  or collapsing (F2). The G-T2 claims the implementation discharges with
  tests are G-T2a (against `F_C`) and G-T2b (three classes, the class-3 shape
  pinned) — the amended contract, not the original (F1).
- **A2 (Verus, deferred by ruling until after A1).** The candidate theorem
  is G-T2a without the bound: `∀ S well-formed: C(lfp F_G(S)) ≤ lfp F_C(C(S))`,
  by induction over iterations with K11's one-step lemma — a compact
  statement over `Lattice` and `System::step`, no allocation, no `unsafe`,
  finite domains. Verus-shaped, and now a theorem that is true as stated. A
  second candidate: monotone `F` + finite height + fair chaotic iteration ⇒
  the same lfp as Jacobi (K10's inductive facts, unbounded). Not started:
  proving a contract we had just caught mis-stated would have been the
  classic mistake, and A1 must first use the same kernel API.
- **Not inherited:** any claim about G-T1 as a whole. The precision floor
  from honest facts is K6/K7; the honesty of the facts is Roslyn/CFG/G-V4
  territory and stays in the fixture matrix.

## 8. Owner ruling after A0 (OWNER RULING, recorded; terminal at `9523fac`)

- **A0: PASS / KEEP.** Kani earned its seat: not "a test was missing" but
  two contract defects that would have surfaced inside the implementation —
  finalize-before-apply (F2) and G-T2 being false against the legacy
  derivation (F1). The formal kernel stays in the project permanently.
- **A0.5 (done here): the G-T2 correction**, options (a) + (c), explicitly
  not (b) — a hypothesis "no unresolved callee" would fix the theorem and
  ruin it as a static-analyzer contract. §4 F1 resolution above; P-037 §7,
  §0, §6, §8 rows 12/14/16 and §10 amended; the third verdict-change class
  declared and fenced ("may not change a verdict without a separate declared
  class"); the migration consequence corrected.
- **A2 (Verus): deferred** until A1 uses the same kernel API — then G-T2a
  unbounded, and perhaps the generic lfp / order-independence theorem.
- **CI split (done here):** `ci.yml` job `formal-p037` on every push — fmt,
  clippy, the 37 twins, and the fast harnesses (K1–K9 value-level, K10a,
  K10e step, K11 one-step, K12a: seconds each); `formal-p037-gate.yml`
  nightly and on demand — K10b, K10c, the K10e whole-solver pair, the K11
  lfp forms, K11b, K11′, K12b (≈ 15 min). A red nightly is a finding, never a
  flake: every harness is deterministic.
- **Formal-checkability as a *local* design constraint of the kernel, not a
  dictate to the system:** keep the semantic kernel value-oriented (copy at a
  symbolic index, by-value transforms, plain loops; §2) so it stays
  model-checkable; nothing else in Owen is asked to please CBMC.

### 8.1 A1 — the production guarded-transfer kernel (next; acceptance as ruled)

Move / reuse `formal/p037-kernel/src/lib.rs` into the production summary
engine with minimal changes — the promise of A0, not a rewrite "inspired by"
it. First bug: the `ConsumesParam` may-as-must hole
(`p036-bakeoff.md` §3.1, branch `claude/p036-capability-bakeoff-fzw74t` at
`ce2e6bc` — §9). Acceptance, verbatim from the
ruling, made checkable:

```text
A1 ACCEPTANCE
1. F3-S1..S4 (corpus/p036-bakeoff guarded-consume-*): correct guarded-transfer
   verdicts — Teardown(true) keeps the obligation (OWN001), Teardown(false)
   consumes, the wrapper and negation wrappers inherit the split.
2. Existing transfer corpus (corpus/real-world, corpus/wpf, corpus/di, the
   #305 fixtures): zero unintended regression — every difference in a
   collapsed-view diff falls in one of the three declared classes.
3. Unknown guard: may / unknown -> plain + OWN051, never consume.
4. Application on FINALIZED state only: a raw solver cell is never consumable
   (kernel K7 witness ported as a production test).
5. G-V4 failures — mutable / ref / out / aliased guard: the edge degrades to
   opaque, never fabricates must (P-037 §8 rows 18-19 as fixtures) — on BOTH
   layers: no fabricated `release` op at the call site in the emitted facts
   (extractor-fact acceptance) AND no false OWN003 end to end
   (`scripts/p037_controls.py --post-a1`, the three KNOWN_FALSE_POSITIVE
   controls turning red -> green).
6. The formal kernel's twins run over the SAME production functions, not a
   copy: the kernel is moved, its properties move with it.
7. Kani: value-level harnesses mandatory (PR gate); solver-heavy harnesses
   opt-in / nightly.
8. The F1 pin: `if (g) p.Dispose(); else Extern(p);` with Extern unresolved
   yields the collapsed value UNKNOWN (class 3), lowered to plain + OWN051 —
   an implementation that "repairs" it to legacy's optimistic MAY fails;
   on the facts layer the call site carries no release op (today it does:
   the class-3 control's `current` record), and the OWN051 advisory appears.
```

**The gate, as a REPOSITORY FACT that needs a ruling before any production
line changes.** P-037 §10: "nothing here may be implemented in Python (a
moving parity target) or in Rust (a deliberate divergence) before the P-022
cutover; the implementation home is the post-cutover summary engine (#304)".
P-022's status (`docs/proposals/README.md`, step 8): Stage 1 (opt-in Rust
behind the launcher) and Stage 2 (Own.NET's own CI and dogfood on Rust)
have landed; **Stage 3, the public cutover, has not** — it "needs its own
authorization"; Python remains the public default and the reference on all
four launcher surfaces. The production summary engine today is therefore
*two* engines kept byte-equal by the differential oracle and the compare
gates: `ownlang/ownir.py` (`Transfer` + `join` at the top, `PathAction` /
`ParamSkeleton` / `MethodSkeleton` / `ParamSummary` / `MethodSummary`,
`solve_with_log` with its `lookup` / `contrib` and the `⊥ → no`
finalization, `_build_skeletons` with the release-priority ladder,
`_lower_fn_params` as the INF-A1 application) and its mirror
`rust/crates/own-bridge/src/mos.rs` (`Transfer`, `ParamSummary`,
`MethodSummary`, `solve_with_log`, `solve`) with `lower.rs::lower_fn_params`.
Landing P-037 in one engine only would make the Stage-2 compare gates
diverge, which is exactly what they exist to refuse. The options that were
put to the owner, with the ruling that followed:

1. **Wait for Stage 3** (P-037 §10 literally): A1 starts when the Rust core
   is the only engine to change. The kernel is ready; nothing is lost but
   time.
2. **Authorize a dual-engine landing now**: Python-first as the reference
   (the moving parity target moves once, deliberately), the Rust mirror in
   the same PR series, the collapsed-view diff against the golden dumps as
   the parity witness, the exclusion ledger untouched. Roughly twice the
   work of a single-engine A1 and it keeps every existing gate honest.
3. **Authorize a Rust-only landing behind `--engine rust`** with a declared
   compare-mode boundary for the P-037 verdict-change classes. Cheapest, but
   it turns the shadow gates' "zero acceptance-unexplained" into a ledger
   entry, and the public engine would not carry the fix.

```text
OWNER RULING (2026-09-18)

Choose option 1.

A1 production implementation MUST wait for completion of P-022 Stage 3.

Do not implement P-037 in Python.
Do not implement P-037 in the Rust production engine before cutover.
Do not introduce a declared compare-mode exception for P-037.
Do not weaken, reinterpret, or bypass the P-022 zero-diff/cutover boundary.

A0/A0.5 and all non-production A1 preparation are complete and may remain.

The next legitimate transition for A1 is:

    P-022 Stage 3 complete
        ->
    Rust is the production/default core
        ->
    land A1 in the Rust summary engine using the checked kernel
        ->
    discharge the P-037 acceptance matrix and formal gates.

P-022 Stage 3 must be decided on its own evidence and must not be accelerated
or re-scoped merely to unblock P-037.
```

Why not option 2, in the owner's words: a dual-engine A1 changes the
reference and the shadow at the same time for a new verdict-changing
feature; zero-diff stays green because both sides are changed identically,
and the compare gate stops answering the question it exists for ("does Rust
reproduce the frozen Python behaviour?") and starts answering "do two
implementations of a new feature, written together, agree?" — a convenient
way to win parity against oneself. Why not option 3: a Rust-only
pre-cutover landing creates a deliberately *explained* diff in exactly the
period when P-022 is proving the absence of such diffs; the exclusion
ledger grows, and the migration gate turns into a Christmas tree. This is a
**sequencing dependency, not a blocker to route around**: A1 is ready on
the starting line and loses nothing by waiting — and after Stage 3, Python
need not learn P-037 at all if its role becomes legacy / reference /
rollback under #262, so waiting also removes the need to implement a
non-trivial semantics twice right before one implementation stops being the
production core.

State, as ruled:

```text
A0            9523fac   PASS / KEEP                                   DONE
A0.5          7cf1f93   G-T2a / G-T2b, formal CI split                DONE
A1 PREP                 kernel, fixtures, seam map, acceptance        DONE
A1 PRODUCTION           BLOCKED BY DESIGN — guard: P-022 Stage 3 complete
```

Allowed until Stage 3 (non-production work around A1 only): the formal
kernel and its CI; the regression anchors already in place (F3-S1..S4, the
F1 witness); the documented mapping kernel → Rust summary engine (above);
fixture families for the G-V4 / trusted-input assumptions (§8.2); the
backlog item with the exact acceptance (#304 is the post-cutover tracker).
Not allowed: any change to `ownlang/ownir.py`, `rust/crates/own-bridge`, or
launcher-visible behaviour.

The A1 preparation that is engine-independent is done: the kernel API
(`Transfer`, `Cells`, `Election`, `import`, `read`, `contribute`, `solve`,
`apply`) is what `mos.rs` would call; the seam is the per-parameter
`ParamSkeleton` path actions (cells and edges are their guarded form),
`solve_with_log`'s lattice (the kernel's `Lattice` for `Cells`) and
`lower_fn_params` (the kernel's `apply`, finalized input only).

### 8.2 G-V4 / trusted-input negative controls (class 4, executable today)

The kernel trusts three things (§5); P-037 §8 rows 18–19 and the G-T2b
class-3 shape are their negative controls, now executable fixtures under
`corpus/p036-bakeoff/` (`control.cs` + an empty `expected-diagnostics.txt`:
the required verdict at `--severity warning` is *no findings*, today and
after A1 — a fabricated `must` would surface as a false OWN003 on the
honest defensive dispose each control carries):

| fixture | P-037 | what a wrong kernel would do | measured today (MEASURED OBSERVATION) |
|---|---|---|---|
| `gv4-control-mutated-guard` | §8 row 18a | read `Inner(p, g)` after `g = !g` as an `id` edge, select `must`, charge the defensive dispose OWN003 | **OWN003 (false positive)** on `r.Dispose()` — the may-as-must `ConsumesParam` lowers `Inner(p, g)` to a release because `Inner` disposes on some path; the mutated guard never gets a say |
| `gv4-control-ref-alias-guard` | §8 row 18b | same through `ref bool a = ref g; a = !a;` | **OWN003 (false positive)** — same mechanism |
| `gv4-control-aliased-self-null` | §8 row 19 | a self-null `must` on `q` after `ref Stream a = ref q; a = r;`, charging the caller's `s.Dispose()` | **OWN003 (false positive)** on `s.Dispose()` — `q.Dispose()` somewhere in `Close` ⇒ the call is a release of the caller's argument, which the alias write makes untrue |
| `legacy-honesty-else-unresolved-forward` | G-T2b class 3 | "repair" the guarded `unknown` to legacy's `may` (value level; verdict-equivalent) | 0 findings (plain + OWN051 for the unknown guard) — as required |

These are conformance anchors for A1, not bakeoff cases: the bakeoff
manifest does not list them, the benchmark does not scan them, and today's
measurement is recorded so that A1 cannot change it unnoticed. **Three of
the four are red today**: the measurement turned a design-level worry
(G-V4: "a wrong kernel *would* fabricate `must`") into a production fact —
Owen at `70189a3` already charges the honest defensive dispose a false
OWN003 on every G-V4 shape, not through any guard reasoning but through the
flow-insensitive `ConsumesParam` that the bakeoff note §3.1 documented as
may-as-must. Confirmed at the facts level: `own-check.sh --emit-facts` on
`gv4-control-mutated-guard` emits, for `Guarded.Use`, a
`{"op": "release", "var": "r", "line": 36}` for the `Outer(r, true)` call
itself, beside the explicit release at line 37 — the consume is decided in
the extractor before either engine runs, which is also why both engines
agree on the false positive. That is the bug the owner named as A1's first
target, now with
three executable witnesses that fail until it is fixed and must pass
without a fabricated consume appearing anywhere else. It lives in the
extractor (`frontend/roslyn/OwnSharp.Extractor/Program.cs`), which both
engines share. The owner ruled on the carve-out question the same day:

```text
OWNER RULING — ConsumesParam false OWN003 controls (2026-09-18)

The three newly measured false-OWN003 cases are accepted as
pre-A1 regression anchors, not as authorization for a pre-cutover fix.

Do NOT change Roslyn ConsumesParam semantics before P-022 Stage 3.

Reason:
- the defect is launcher-visible;
- fixing it changes interprocedural inference verdicts;
- the P-022 freeze is on verdict-changing inference, not merely
  on Python/Rust divergence;
- the shared-extractor location therefore does not create an exception.

#305 is not controlling precedent:
- it repaired bounded P1 false-negative soundness holes in teardown
  crediting under the explicit pre-cutover floor doctrine;
- this defect is a false-positive / precision failure in cross-call
  consume inference and is the first target of post-cutover A1.

Keep the three failing controls exactly as measured.
They become mandatory red→green acceptance witnesses for A1 after Stage 3.

No production fix before cutover.
```

In the owner's words on why a "small bounded fix" is a trap here: the
moment `ConsumesParam` is restricted to unconditional disposes, the next
questions are `if (x) Dispose(); else Dispose();`, early return,
`try/finally`, the self-null guard, forwarding helpers, exception paths,
guards on parameters vs locals vs fields, callee forwarding into another
consumer — three patches later the guarded-summary semantics is being
written into the Roslyn extractor under the name of a bugfix, which is the
road the bakeoff already mapped. The freeze stopped exactly the kind of work
it exists to stop; drilling neat holes in it right after it first worked
would be comic.

**Consequences applied.** The controls no longer carry an empty
`expected-diagnostics.txt` that would read as "clean today": each has an
`expected.json` with `classification` (`KNOWN_FALSE_POSITIVE` for the three
G-V4 controls, `VERDICT_COMPATIBLE_VALUE_DIFFERENCE` for the class-3 shape),
the `current` record measured at `70189a3`, and the `post_a1` acceptance —
so the evidence lies about neither. `scripts/p037_controls.py` checks them
on **two layers**, because the facts showed the defect is decided before the
engine boundary: (1) the extractor-fact layer — does the call site carry a
fabricated `release` op in the emitted facts; (2) the end-to-end layer — the
finding codes at `--severity warning`. Default mode checks `current` and
must pass today (a mismatch means Owen's behaviour moved and the record must
be re-measured, never silently); `--post-a1` checks the acceptance and is
expected to fail until A1 lands after Stage 3. Two layers so that a Rust
summary engine can never compensate a bad extractor fact with another
heuristic and hand A1 a green end-to-end result over a still-broken seam.
Measured today, all four controls carry the fabricated release at the call
site — including the class-3 shape, where it also suppresses the OWN051
advisory the unknown guard should earn (0 findings either way at warning
severity: verdict-compatible, value-different, exactly class 3).

## 9. Port provenance and the post-cutover re-measurement (A1.0)

> Status: **A1.0 bootstrap. No production verdict changes.** Everything in
> this section is bookkeeping and evidence; the A1 semantics is §8.1 and has
> not started.

### 9.1 Where this tree's P-037 assets came from (REPOSITORY FACT)

A0, A0.5 and the control authoring all happened on branch
`claude/p036-capability-bakeoff-fzw74t`, which also carried the P-036
comparative bakeoff. That branch was **not merged and not cherry-picked
wholesale** — by owner instruction, because the bakeoff's raw evidence is 846
files of six tools' output over a corpus, none of which A1 needs and all of
which would have arrived as unreviewed payload behind a P-037 change.

Instead the P-037 assets were **ported by path** onto a branch cut fresh from
post-cutover `main`. The source tree is terminal `ce2e6bc`; its merge base
with `main` is `70189a3`, which is also the commit the `current` control
records name. The work those paths carry, oldest first:

| commit | what it added |
| --- | --- |
| `0355bdd` | A0 kernel spike — the pure guarded-transfer algebra, Kani harnesses and test twins |
| `96bdac3` | small-width symbolic inputs, so CBMC stops bit-blasting 64-bit fields |
| `30fc9f0` | tractable solver harnesses — plain kernel loops, inductive one-step proofs |
| `919a908` | read coordinates by value at symbolic indices |
| `6419b33` | `collapsed()` and `today()` as by-value transforms |
| `9523fac` | A0 terminal — 22 of 22 Kani harnesses proven |
| `7cf1f93` | A0.5 — G-T2 split into G-T2a / G-T2b; the kernel G-T2b harness; the formal-kernel CI split |
| `7751d1b` | the A1 sequencing ruling (wait for P-022 Stage 3); G-V4 negative controls, measured red |
| `ce2e6bc` | the owner ruling on no pre-cutover `ConsumesParam` fix; `current` / `post_a1` expectations; the two-layer checker |

**Deliberately not ported**, and the reason in each case:

* `docs/evidence/p036-bakeoff/raw/**` (846 files — CodeQL, .NET analyzers,
  RLC, Owen, Infer#, IDisposableAnalyzers) and `custom-codeql/`: P-036
  bakeoff evidence. A1 does not read it.
* `scripts/p036_bakeoff.py`, `docs/notes/p036-bakeoff.md`: the bakeoff's
  runner and note. The note is still the citation for the SHRINK hand-off, so
  the three places that cite it now name the branch and `ce2e6bc` instead of
  a relative link that would dangle in this tree. **The claim was not
  weakened to fit the port — the pointer was made honest about where it
  lives.**
* `corpus/p036-bakeoff/{enrollment-*, loop-no-progress-through-helper,
  obligation-barrier-through-helper, mixed-release-forward-use-after,
  nullguard-helper-use-after, release-through-delegate-target,
  subscription-release-skipped-by-throw}`: bakeoff cases for P-036 vertical B
  (LifecycleEnrollment, exceptional exits). Not A1's subject. 8 of the 18
  case directories came across; 10 did not.

The directory keeps the name `corpus/p036-bakeoff/` on purpose. It is where
these cases were authored, the checker's `CONTROLS` path points at it, and
renaming it would make every future diff against `ce2e6bc` — the only tree
that can corroborate this port — noise. The name is provenance, not a claim
about scope.

The `docs/proposals/README.md` **P-036 row was left untouched** by this port.
The source branch's version of that row cites `docs/notes/p036-bakeoff.md`,
which is not in this tree; importing a dangling link into the proposals index
to carry P-036 bookkeeping through a P-037 change is not a trade worth making.
Only the P-037 row moved, and it moved to say something true in this tree:
Stage 3 landed, so the ruling's post-cutover condition on implementation is
met.

### 9.2 Phase 0.1 — the `current` record re-measured after the cutover (MEASURED OBSERVATION)

The `current` records were measured at `70189a3`, **before** P-022 Stage 3.
At that commit a bare `scripts/own-check.sh` invocation meant the Python
core. Since `#262` Stage 3 (merged as `#359`, `main` at `63148d0`) the same
bare invocation means Rust. A record whose meaning silently changes under it
is not a record, so it was re-taken before A1 was allowed to rest on it.

Re-taken, **not rewritten**. `measured_at: "70189a3"`, `current` and
`post_a1` are byte-identical to the source branch; each `expected.json` gains
an append-only `remeasured[]` entry (schema `p037-control-expectation/2`),
and the checker accepts schema `/1` and `/2` alike.

Measured at `main` `63148d0` plus this port, which adds no file under
`frontend/`, `ownlang/` or `rust/` — verified against the port's changed-path
set, not assumed:

```text
P-037 controls — checking the current record (measured at 70189a3), engine=both
ok  gv4-control-aliased-self-null           engine=python findings=['OWN003']  fabricated@29=True
ok  gv4-control-aliased-self-null           engine=rust   findings=['OWN003']  fabricated@29=True
ok  gv4-control-mutated-guard               engine=python findings=['OWN003']  fabricated@39=True
ok  gv4-control-mutated-guard               engine=rust   findings=['OWN003']  fabricated@39=True
ok  gv4-control-ref-alias-guard             engine=python findings=['OWN003']  fabricated@36=True
ok  gv4-control-ref-alias-guard             engine=rust   findings=['OWN003']  fabricated@36=True
ok  legacy-honesty-else-unresolved-forward  engine=python findings=[]          fabricated@41=True
ok  legacy-honesty-else-unresolved-forward  engine=rust   findings=[]          fabricated@41=True
RESULT: all match            (--post-a1: MISMATCH 4/4, rc=1, as designed)
```

**Result: UNCHANGED, on both layers, under both engines.** Stage 3 moved none
of these four controls, so the Phase-0 STOP condition — "if the cutover
changed any of this, classify it before implementing A1" — did not trigger.

That the two engines agree here is not a lucky break, it is the two-layer
design paying out: the fabricated `release` is emitted by the **Roslyn
extractor**, before either engine sees a fact, so no engine choice can move
it. This is the same reading §8.2 arrived at from the facts, now confirmed by
running both engines against the same record.

`INFERENCE`, and worth stating as one rather than as a result: A1's first
target is therefore extractor-side, and a fix that showed up only under
`--engine rust` would be evidence of a **second** mechanism, not of the fix.

### 9.3 What the port had to adapt, and why (REPOSITORY FACT)

Three adaptations, each a consequence of the cutover rather than a
preference:

1. **`scripts/p037_controls.py` now passes `--engine` explicitly** (default
   `rust`; `python` measures the reference; `both` measures each against the
   same record and reports agreement). On the source branch it invoked the
   launcher bare. Post-cutover that is wrong twice over: on a machine with no
   Rust candidate it exits 2 having measured nothing, and where it does run
   it would silently have changed which engine the `70189a3` record is about.
   `both` agreeing is an OBSERVATION and is **not** contracted — A1 changes
   the Rust engine and not Python, so a later divergence there is a finding to
   classify, not a failure to paper over.
2. **The `formal-p037` job keeps `toolchain: stable`**, matching `rust-core`
   directly above it in `ci.yml`. The concrete rustc pin that Stage 3
   requires is a property of `action.yml` — the consumer-facing distribution
   surface, where a moving toolchain moves what users get — and not of this
   repository's own CI, which is where a moving toolchain is supposed to
   break us first. `tests/test_stage3_surfaces.py` reads `action.yml` for
   that check and is unaffected; it was run and is green.
3. **Three citations of `p036-bakeoff.md` now name the branch and commit**
   they live at, per §9.1.


## 10. A2 execution governance freeze

This section is the implementation-governance checkpoint for A2.0 through
A2.2. It records owner rulings that were made after A1.1-a1 and before the
first guarded-fact vocabulary change. These are not new semantics: they are
the staging rules required to implement the already-frozen P-037 contract
without moving the semantic boundary accidentally.

### 10.1 New-finding classification

After this freeze, a new implementation finding belongs to exactly one of
these classes:

1. it contradicts the frozen P-037 contract -> **implementation defect**;
2. it exposes an unrecorded theorem assumption -> **proof-boundary manifest
   amendment**;
3. it exposes an unrepresented syntax/fact shape -> **shape-census
   addition**;
4. it exposes a missing test/control -> **evidence-infrastructure
   addition**;
5. it requires new semantics or changes a frozen rule -> **STOP: explicit
   contract amendment before implementation continues**.

Cases 1--4 do not reopen the architecture. Case 5 is the only architecture
door.

### 10.2 A2 raw-fact boundary

The Roslyn frontend reports source facts; it does not run P-037 summary
semantics in order to describe them.

For boolean arguments the raw vocabulary distinguishes literal true, literal
false, a stable parameter, a single negation of a stable parameter, and
opaque.

For reference arguments the raw vocabulary distinguishes:

- `NullLiteral`;
- `ObjectCreation`;
- `StableParam(parameter_id)`;
- `CallResult(callee_id, signature)`;
- `Opaque`.

The frontend never emits `fresh_owned`. Freshness of a call result is a
summary conclusion, not a Roslyn fact. A `CallResult(F)` may therefore select
the positive nullness cell only at G-A1 application, after summaries are
finalized and only when `F` is proven to return fresh; otherwise it is
opaque/collapsed. Using `CallResult` to choose a solver-edge transform would
make the pre-solver system depend on the value solver's own output and is a
case-5 STOP.

For a nullness guard, forwarding the same stable nullable reference is
identity of the predicate, not truth of it: it is an `id` relation, never
`const-pos`. `const-pos` is reserved for statically proven non-null
arguments under G-A1: object creation, or a call result whose finalized return
summary proves fresh. `null` is `const-neg`. No Roslyn nullable-flow
judgment is part of this contract.

### 10.3 A2 staging invariant

A2.1 makes the guarded-fact sidecar a known, fail-loud OwnIR vocabulary on
both Python and Rust doors. A2.2 emits honest facts for every relevant call,
including calls the legacy `ConsumesParam` path currently classifies as
consuming. The legacy body remains authoritative through A2: the sidecar is
validated but semantically inert.

Therefore A2's three evidence layers are:

- fact shape: expected, deliberate change;
- whole MOS document: no change;
- public verdict: no change.

A valid but deliberately contradictory sidecar is the named inertness
control: in A2 it must alter neither MOS nor verdict. In phase B the same
fixture flips to a required-read control for the guarded shadow path.

### 10.4 Phase-B proof boundary

Phase B may not begin semantic wiring until the P-037 proof-boundary audit is
green. The audit must derive the Kani harness inventory from source/Kani,
check that the fast and heavy CI sets are disjoint and their union equals the
source set, record the human claim and production subject for every harness,
and make every load-bearing assumption traceable to either a production
guarantor or an explicit `OUTSIDE_KANI_BOUNDARY` entry.

The bounded formal model is intentionally not the production storage model:
the current harness system uses three coordinates and two edges per
coordinate. Production reuses the same guarded algebra and one-step
semantics through a dynamic driver; the bounded adapter remains the model
checker instance. The production-size bound is therefore explicit outside
the proof boundary, not implied to have been proved.

Non-vacuity is required per load-bearing restriction, not mechanically one
`kani::cover` per `kani::assume`. Negative controls must pin the production
guarantors for well-formedness and application ordering.

### 10.5 Governance before the semantic cut

Before phase C makes guarded Rust summaries authoritative, two P-022 policies
must be re-scoped explicitly:

- shadow compare may accept only machine-classified, per-document P-037
  differences in the three declared classes
  (`APPLICATION_REFINEMENT`, `SUMMARY_REFINEMENT`,
  `LEGACY_HONESTY`); every other difference remains
  acceptance-unexplained and fails;
- the Stage-3 rollback contract separates rollback mechanics, exact parity on
  an unaffected sample, and classified intentional P-037 divergence. Python
  remains the legacy/reference/explicit rollback engine; it does not gain a
  second guarded implementation merely to preserve zero-diff.

After the semantic cut, a separate C+ checkpoint canonicalizes the temporary
double representation of call facts. A stable call-site identity is introduced
in A2 so the legacy and sidecar views cannot silently drift before that
canonicalization.

### 10.6 A2.2 freeze: relevance taxonomy, named exclusions, orphan carrier

OWNER RULING, recorded 2026-09-19 after A2.1 closed and before the first
A2.2 code change; corrected once, before any code, after an independent
review of the first freeze commit (10.6.0). Nothing here is new semantics: it
fixes what "every relevant call" means before anyone tries to be complete
about it, because the 28-case probe below shows that the A2.1 sidecar captures
two argument shapes out of twenty-eight correctly (the bare identifier and the
parenthesized one) and two falsely (a boxed struct handle, and a delegate
invocation recorded as a plain call of the delegate's `Invoke`), and that the
naive repair ("the handle occurs somewhere
below the argument, therefore the call is relevant") would prove nonsense with
full confidence. The machine-readable form of this section is
`corpus/p037-relevance/registry.json`; `tests/test_p037_relevance_freeze.py`
keeps the two from drifting.

#### 10.6.0 Provenance: how A2.1 actually closed, and this freeze's own (REPOSITORY FACT)

    T   4a8e6582   terminal-green baseline commit; R = 5fd6bfa6 (PR #361)
     \
      dce26ed     A   original A2.1 treatment — SUPERSEDED, evidence-inadmissible
          |
      5a0de070    A'  corrected A2.1 treatment (PR #363)
          |
      cd7e020     S'  corrected A2.1 after-evidence at A'
          |
      23e3203     main, merge of PR #363

A (`dce26ed`) emitted the sidecar with a contract bug: a handle argument that
had to be encoded `opaque` (a `params` slot, `ref`/`out`, an unstable owned
parameter) also had its relevance bit zeroed, so the whole call record vanished
instead of surviving with an opaque slot, against spec §5.2. A' (`5a0de070`)
decouples relevance from representability for that family and pins it with
three census shapes (`corpus/p037-shapes/sidecar-relevance-*`). S' (`cd7e020`)
is the M1 after-evidence at A' against R with population T: all four pairs
UNCHANGED, facts moved on 1/1 repo and 36/137 corpus documents, execution
profile byte-identical to the baseline capture, own-cli's qualified digest
unchanged from T. A's SHA is retired, not reused; A's evidence (PR #362) is
stale and unmerged. A2.1 CLOSED means A' + S' in `main`, nothing else.

This freeze's own provenance: the first freeze commit, `ee4d065` on
`claude/p037-a1-production`, has parent `dce26ed` — it was cut on superseded A
and measured its probe there. It is **superseded for a provenance defect** (a
freeze accepted on buggy A and later stapled to the corrected A2.1 would say
exactly what the provenance discipline exists to prevent). This section lives
in F0', a fresh commit on `claude/p037-a2.2` with parent `23e3203`; the probe
was re-measured on A' (`5a0de070`, whose extractor is byte-identical to the
merge's), not assumed. A freeze is not measurement evidence, so nothing about
`ee4d065` is worth preserving beyond this sentence.

Two consequences carried from A2.1 as landed. The sidecar is validated by the
producer and inert, but not yet *known* to either door: Rust carries
`guarded_facts` as an unknown flattened field and the Python loader ignores
the key, so the "known, fail-loud on both doors" clause of §10.3 is deferred to
the step that registers the sidecar at the doors, an instrument change that
opens a new T/R round; until then `sourceSite` is UNBOUND (type only) per
spec/OwnIR.md §4.2. And R stays valid for A2.2's after-comparison: same
instrument, same population T.

#### 10.6.1 Completeness (OWNER RULING, verbatim)

> Completeness means every candidate occurrence at a call-related syntax site
> is either represented by the raw guarded-call vocabulary or assigned exactly
> one named exclusion. Occurrence alone does not establish ownership flow to
> the enclosing callee.

So `Relevant(call, arg)` is **not** "an identifier bound to a handle occurs
anywhere below `arg`". Relevance is decided by a deliberately small value-flow
recognizer (10.6.2), semantic where syntax lies (10.6.3). The broad oracle
stays — every symbol-bound candidate occurrence in a call-related context —
but its output per occurrence is *captured by a relevant call fact* OR
*classified by exactly one named non-flow / indirect-flow rule*, never "every
occurrence must become a call fact". An unclassified occurrence is red, by
rule name and coordinate. The oracle is an over-approximation whose job is to
demand explanations; it is not the specification of flow, so it can never make
the completeness checker more semantically brave than P-037 itself.

#### 10.6.2 Relevance taxonomy (OWNER RULING)

- **direct** — the argument expression *is* a handle identifier (a disposable
  candidate local or an owned parameter of this method), or the handle is the
  receiver of a reduced extension method (declared ordinal 0 in the unreduced
  declaration), reaching the parameter through no conversion or a built-in
  value-preserving one. Represented as `var` / `param`.
- **transparent** — the handle under a transparent wrapper: parentheses, the
  null-forgiving `!`, or a cast / `as` whose *semantic conversion* is built-in
  and value-preserving (identity, or a guaranteed reference conversion) and
  invokes no user-defined operator. Same value; relevance kept; represented as
  the unwrapped fact.
- **may-value** — the argument's value is one of several alternatives and a
  handle is among them, reachable through allowed value-preserving edges only:
  the conditional operator, `??`, a switch expression, and an `as` whose
  conversion may fail to null. Relevance kept; representation stays `opaque`.
- **call-like** — a genuine call site that is not an invocation expression:
  object creation (the constructor is the callee), delegate invocation, and,
  since A2.2-4R5, a constructor initializer (`: base(...)` / `: this(...)`,
  the target constructor is the callee). Each gets its own call fact; one
  semantic family per A2.2 commit.
- **indirect** — the handle occurs below the argument but the value that
  reaches the callee is something else (a call result, a container, a tuple, a
  closure, a converted value), or the site binds no summary parameter at all
  (an ordinary receiver, a storage assignment, a method group). Not relevant
  to the enclosing callee; every such occurrence matches exactly one named
  exclusion.

Invocation results, object/array/collection construction, tuple construction
and lambdas do **not** propagate relevance outward merely because a handle sits
somewhere in their subtree.

#### 10.6.3 Conversions decide, syntax does not (OWNER RULING)

The first freeze said "explicit cast → same value" and "user-defined
conversion → exclusion" at once, which overlap on `TakeBox((Box)r)` with an
`explicit operator`: a cast by syntax, a hidden call by semantics. The freeze
must give one answer, and it is the semantic one:

- **transparent** = parentheses, `!`, and built-in identity or
  reference-preserving conversions that invoke no user-defined operator,
  whether implicit at the parameter or written as a cast / `as`;
- **user_conversion** (an exclusion) = any conversion edge whose Roslyn
  semantic conversion is user-defined, implicit or explicit, including one
  hidden inside a cast expression. This rule wins over any transparent-looking
  syntax around it;
- `as` is **not** transparent by SyntaxKind: `r as Stream` on a `MemoryStream`
  is a guaranteed reference upcast and transparent; `p as Derived` on a base
  type may turn a non-null handle into null and is may-value, `opaque`;
- the same edge rule reaches inside `?:`, `??` and `switch`: an arm is a handle
  alternative only if it yields the handle through allowed value-preserving
  edges. An arm that passes through `op_Implicit` is not one.

Therefore A2.2-1's recognizer is not "SyntaxKind plus `GetConversion` on the
argument": `(Box)r` already has type `Box` at the call, so the argument's own
conversion is identity and the user-defined one sits inside the cast
expression. The recognizer is a small value-flow walker over Roslyn
`IOperation`, `ClassifyValueFlow(operation, handle) -> Direct | MayValue |
Indirect(named_exclusion) | None`, checking the semantic conversion at every
`IConversionOperation` on the path and the argument's `InConversion`. The
registry freezes the conversion-edge vocabulary and the rules binding it to
the classes; the structural test proves no probe row is both transparent and
user_conversion, that both user-defined kinds and the `as` split are pinned.

**Conversion closure (A2.2-1a, OWNER RULING).** Two edges the first freeze
left implicit are named, without any production change; A2.2-1's walker
already behaves this way, and the census now says so by name:

- `reference_checked` — a built-in *explicit* reference conversion (a downcast,
  or interface to class / interface). When it succeeds the callee receives the
  same object reference; when it fails it throws before the call, so no
  argument value is produced and the call is not entered. A failure is not an
  alternative value, which is exactly what separates it from `as`:
  `(Derived)r` is *same reference or no call* and therefore **transparent**,
  while `r as Derived` is *same reference or a null value* with the call
  continuing, and therefore may-value. Turning a precise `var r` into `opaque`
  merely because the freeze had said "guaranteed" would have been an
  artificial loss of information; the registry was behind the code and the
  spec, and it is the registry that moved.
- `boxing` — a disposable *struct* handle passed to `object` or an interface
  is boxed: the callee receives a copy, never the ownership identity of the
  value. Not direct, not transparent; the named exclusion is
  `boxing_conversion`. This was not left for A2.2-4's oracle to "discover":
  a known unclassified point contradicts the completeness sentence today. No
  `other_conversion` bucket exists either — a bucket is a bin, and it would
  kill the point of a hostile oracle; a genuinely distinct conversion the
  oracle meets is a §10.1 case-3 addition with its own name.

The closed vocabulary is therefore none, identity, reference_upcast,
reference_checked, may_fail_null, user_defined_implicit,
user_defined_explicit, boxing, not_applicable; the value-preserving edges a
direct or transparent row may carry are the first four. Measured, not
assumed: the A' producer captured `Sink(r)` on an owned struct parameter as a
`param` fact (a false raw fact), and the A2.2-1 walker stops at the boxing
edge; A2.2-1a pins both rows in the probe and in two census shapes.

A' already landed this separation for one family: a `params` slot, a
`ref`/`out` argument or an unstable owned parameter is `opaque` and keeps the
call relevant. A2.2-1 extends the same separation to the transparent and
may-value classes.

#### 10.6.4 Named exclusions

`nested_call_result` (`Use(Wrap(r))`: `Wrap(r)` is direct and owed its own
call fact; `Use` receives a call result), `container_construction`
(`Use3(new Stream[] { r })`, `new List<Stream> { r }`: the container flows),
`tuple_construction` (`Use2((r, 1))`), `closure_capture` (`Run(() => Use(r))`:
the closure flows; the call inside belongs to the lambda body, spec §5.2),
`method_group_conversion` (`Run(r.Dispose)`: the delegate flows),
`receiver_not_summary_parameter` (`r.CopyTo(...)`: an ordinary receiver has no
declared ordinal; a summary of `this` is a §10.1 case-5 amendment),
`storage_assignment` (`d[0] = r`, a property or a field: an assignment is not a
call site), `user_conversion` (10.6.3: `TakeBox(r)` through an implicit
operator, `TakeXBox((XBox)r)` through an explicit one), `boxing_conversion`
(10.6.3: a disposable struct handle boxed into `object`), `nameof_operand`,
`member_access_on_handle` (`Use5(r.Length)`), and, named by the A2.2-4R4
ruling (10.6.10) after the completeness oracle met them: `predicate_result`
(`Use6(r != null)`: the predicate's bool flows, not the handle),
`interpolation_hole` (`Use4($"{r}")`: the built string flows),
`indexer_argument` (`d[r] = 1`: the handle is an argument of the indexer
accessor's call, a call site the frozen vocabulary deliberately leaves out,
stated in the definition rather than hidden by the name).

Every exclusion carries a positive fixture (the rule fires, no call fact for
that site) and a negative fixture (a syntactically adjacent case that is
captured instead); A2.2-4 checks both by name (10.6.10: the completeness
oracle reads every probe row and every generated hostile case against its
designed classification). Known gap, recorded as a §10.1 case-3 census finding
and not repaired by pretending: lambda and local-function bodies have no
function record of their own, so the calls inside them are unobserved through
A2; the oracle counts those occurrences and their inner call slots.

#### 10.6.5 Representation rulings (OWNER RULING)

- **No `mentions` in the production sidecar.** `opaque` stays opaque, as frozen
  in spec/OwnIR.md §5.2 and §10.2. A `mentions` list may exist in oracle and
  debug records only. The reason is not aesthetic: phase B must not be tempted
  to read "r occurred inside the expression" as an ownership edge. For
  `Inner((Stream)r)` that would be a may-flow of the same value; for
  `Use(Wrap(r))` r flows into `Wrap` and `Wrap`'s result into `Use`; for
  `Use3(new Stream[] { r })` an array flows. One shared `mentions: ["r"]`
  erases exactly the boundary the raw-fact layer exists to keep.
- **Ordinary instance receiver is a named exclusion**, not a pseudo-ordinal:
  no `-1`, no `this`, no `receiver: true`. The frozen OwnIR binds arguments
  and reduced-extension receivers only. Extending the summary domain to
  effect-of-`this` is a case-5 contract amendment, not A2 raw-fact completion.
- **Closure capture is a named exclusion at the outer call**, never a call
  fact with an opaque handle: `Run(() => Use(r))` passes a closure to `Run`,
  not `r`. The inner `Use(r)` is a direct call that belongs to the lambda body.
- Transparent wrappers unwrap to `var` / `param`; may-value keeps relevance
  and stays `opaque`; call-like forms get their own call facts.

#### 10.6.6 The orphan carrier `guarded_functions[]` (OWNER RULING)

The extractor emits a `functions[]` record only for a method the legacy pass
flow-analyses (Program.cs: a method whose every candidate escaped and that
owns no parameter is skipped). Seven of the probe's twenty-eight methods have no
record at all, and with it no sidecar — exactly the methods whose handle left
through a form the legacy cannot follow. The gap is not accepted. Two
tempting repairs are rejected:

- an **unknown top-level key**: both doors would carry it (Rust flattens
  unknown top-level fields, Python does not read them), which buys inertness by
  violating the staging invariant "known, fail-loud vocabulary on both doors";
  a convenient loophole, therefore a suspicious one;
- an **empty `functions[]` record**: `_build_skeletons` puts every named
  function into the first-party universe and creates a `MethodSkeleton` even
  for `body: []`, which can change MOS resolution at callers.

Ruling: a first-class optional top-level carrier, `guarded_functions[]`, each
entry `{name, file, sig, guarded_facts}`, under a strict contract:

- `functions[]` = legacy-visible methods; semantics unchanged through A2;
- `guarded_functions[]` = methods for which guarded raw facts exist but no
  legacy function record does; **producer-validated in A2.2-3P, carried as
  additive unknown metadata by both doors and consumed by neither lowerer
  through A2.2-S; A2.2-D makes it known and fail-loud at both doors**;
- the same method identity in both carriers is a producer defect and a
  refusal (the carrier is an orphan carrier, not a second source for every
  method).

Classification: §10.1 case 3, a previously unrepresented fact shape; no
semantics move.

**Sequencing (OWNER RULING, a §10.1 case-4 clarification recorded before the
carrier was implemented).** The first freeze said "validated by both doors"
and "door validation lands in the instrument step" in one breath, while A2.2-S
promises a comparison against the existing R; the three cannot all hold. The
ruling splits the carrier into two explicit stages:

- **A2.2-3P, orphan carrier production.** `guarded_functions[]` is a declared
  producer/schema fact shape; the producer validates it fail-loud; the Python
  and Rust doors carry it as additive unknown metadata; both lowerers ignore
  it; NO instrument change; the existing T and R stay valid.
- **A2.2-D, door registration.** `guarded_facts` and `guarded_functions`
  become KNOWN, fail-loud vocabulary on both doors, still semantically inert.
  This is the instrument change, it opens a new T/R round, and it comes only
  after A2.2-S. Phase B may start only after A2.2-D's evidence is green.

Registering the carrier at the doors mid-treatment would change the
measurement instrument in the middle of the cumulative A2 treatment and turn
R from a direct baseline into something to be argued equivalent; the split
keeps the experiment that was already assembled meaningful. Phase B builds one
guarded-method view from `functions[].guarded_facts` plus
`guarded_functions[].guarded_facts`; C+ canonicalizes this temporary double
carrier together with the rest of the double representation.

#### 10.6.7 The probe, classified and measured at A' (REPOSITORY FACT)

`corpus/p037-relevance/probe/case.cs`, one method per shape, observed with the
extractor at A' (`5a0de070`): `sidecar_call` = a call fact was emitted,
`record_without_call_fact` = a function record exists but no call fact,
`no_record` = the legacy pass emitted no record at all. The `conversion` column
is the edge from the handle to the parameter as the registry names it.

| method | class | exclusion / form | conversion | A' observed |
|---|---|---|---|---|
| Plain `Inner(r, true)` | direct | | reference_upcast | sidecar_call |
| PlainSame `Same(r)`, `Same(MemoryStream)` non-consuming | direct | | none | no_record |
| Parens `Inner((r), true)` | transparent | parenthesized | reference_upcast | sidecar_call |
| IdentityCast `Inner((MemoryStream)r, true)` | transparent | cast | identity | record_without_call_fact |
| Cast `Inner((Stream)r, true)` | transparent | cast | reference_upcast | record_without_call_fact |
| AsCast `Inner(r as Stream, true)` | transparent | as | reference_upcast | record_without_call_fact |
| Bang `Inner(r!, true)` | transparent | null_forgiving | reference_upcast | record_without_call_fact |
| CheckedRef `TakeDerivedRef((Derived)r)`, r : Base | transparent | cast | reference_checked | record_without_call_fact |
| Ternary `Inner(b ? r : q, true)` | may-value | conditional | reference_upcast | record_without_call_fact |
| Coalesce `Inner(p ?? r, true)` | may-value | null_coalescing | reference_upcast | record_without_call_fact |
| Switch `Inner(k switch {...}, true)` | may-value | switch_expression | reference_upcast | record_without_call_fact |
| AsMayFail `TakeDerived(r as MemoryStream)`, r : Stream | may-value | as_may_fail | may_fail_null | record_without_call_fact |
| Ctor `new Wrapper(r, true)` | call-like | object_creation | reference_upcast | record_without_call_fact |
| DelegateCall `a(r)` | call-like | delegate_invocation | reference_upcast | no_record |
| DelegateCallOwned `a(p)`, p an owned parameter | call-like | delegate_invocation | none | sidecar_call (falsely, as a plain invocation of `Invoke`) |
| Nested `Use(Wrap(r))` | indirect | nested_call_result | not_applicable | no_record |
| ArrayInit `Use3(new Stream[] { r })` | indirect | container_construction | not_applicable | record_without_call_fact |
| CollectionInit `new List<Stream> { r }` | indirect | container_construction | not_applicable | record_without_call_fact |
| Tuple `Use2((r, 1))` | indirect | tuple_construction | not_applicable | no_record |
| Closure `Run(() => Use(r))` | indirect | closure_capture | not_applicable | no_record |
| MethodGroup `Run(r.Dispose)` | indirect | method_group_conversion | not_applicable | record_without_call_fact |
| UserConversion `TakeBox(r)` | indirect | user_conversion | user_defined_implicit | no_record |
| ExplicitUserConversion `TakeXBox((XBox)r)` | indirect | user_conversion | user_defined_explicit | record_without_call_fact |
| NameOf `Use4(nameof(r))` | indirect | nameof_operand | not_applicable | record_without_call_fact |
| MemberAccess `Use5(r.Length)` | indirect | member_access_on_handle | not_applicable | record_without_call_fact |
| Boxing `SinkObject(r)`, r : struct Token, owned parameter | indirect | boxing_conversion | boxing | sidecar_call (false) |
| Receiver `r.CopyTo(...)` | indirect | receiver_not_summary_parameter | not_applicable | record_without_call_fact |
| Indexer `d[0] = r` | indirect | storage_assignment | not_applicable | no_record |

The 22 rows shared with the superseded freeze read the same at A' as they
did at A, as expected: A''s fix touches `params`/`ref`/`out`/unstable-owned
slots, none of which the probe exercises. That is a measurement, not an
inference. One row earned its place by being measured rather than assumed:
`PlainSame`, an identity binding with no conversion at all, has **no record**,
because its callee never disposes the argument and the legacy pass reads a
pass into a non-consuming callee as an escape, leaving nothing tracked. A
direct flow with nowhere to be recorded is the orphan carrier's case (10.6.6)
in its purest form. The `Boxing` row is the one A' capture the walker was
right to lose: A' bound the boxed struct parameter as a `param` fact although
the callee receives a copy, and no A2.2-1 shape covered structs, so the change
was invisible until A2.2-1a measured it. Side observation the oracle will
surface by construction: the
legacy body is itself wrapper-sensitive (`Inner(r, true)` lowers to a release,
`Inner((Stream)r, true)` to a use), so today's verdicts already differ on
semantically identical code. Legacy stays authoritative until C+; this is
recorded, not repaired here.

#### 10.6.8 Out of A2.2: `scope_cache_sites[].file` (#364)

`services[].scope_cache_sites[].file` carries the absolute input path while
every other `file` field is working-directory relative; found because the
repo-population facts digest differed between M1 and another checkout by
exactly three path lengths, with every engine layer identical. It is a found
pre-existing portability defect, not a case-1 P-037 defect (the contract has no
"repo-relative" rule), and it is **not** an A2.2 commit: `scope_cache_sites` is
the DI005 anchor, normalizing it can move an artifact path, and A2.2 must stay
one treatment with one cause of FACT-DIFF. FACT-DIFF is not permission to mix
causes of FACT-DIFF. Tracked in #364 with its own acceptance.

#### 10.6.9 A2.2 order, gate and evidence expectation (OWNER RULING)

- **A2.2-0** freeze the relevance taxonomy and the named exclusions (this
  section, the registry, the probe, the structural test). Gate for the go to
  A2.2-1: F0' parent is `23e3203`; the A' probe re-measured, not assumed;
  this section names A'/S'/merge truthfully; the conversion taxonomy is
  mutually exclusive; user-defined explicit and implicit conversions pinned;
  the `as` split pinned; the freeze test green; CI on F0' green;
- **A2.2-1** decouple relevance from representation properly, with the
  `IOperation` value-flow walker of 10.6.3: parentheses, casts, `as`, `!`,
  conditional, `??`, switch expression; no production `mentions`
  (landed: `268bbd4`, CI green, local rehearsal UNCHANGED on all four pairs);
- **A2.2-1a** conversion closure: `reference_checked` (transparent) and
  `boxing` (the exclusion `boxing_conversion`), registry / §10.6 / spec §5.2
  synchronized, the freeze test expanded, two census shapes added, the
  existing census untouched, no production change and therefore no
  measurement epoch of its own: A2.2-S measures the cumulative treatment
  (landed: `cef567a`, CI green);
- **A2.2-2** constructor and the other genuine call-like forms, one semantic
  family per commit. Object creation landed in the commit carrying this line:
  a constructor call is a call site of its own (`call_kind: object_creation`,
  callee `{Type}..ctor`, arguments bound to the constructor's declared
  ordinals by the invocation mechanism), an object or collection initializer
  binds nothing, a `new` inside another call's argument stays that call's
  `object_creation` fact and propagates no relevance outward; ten
  `corpus/p037-shapes/sidecar-ctor-*` shapes pin it, the 28 earlier shapes are
  byte-identical (landed: `376f2e6`, CI green). Delegate invocation followed
  as its own family, A2.2-2b, in the commit carrying this line: `a(s)`,
  `a.Invoke(s)` and `a?.Invoke(s)` on a delegate-typed `a` are
  `call_kind: delegate_invocation` with callee and sig null and first_party
  false — the target is never guessed — while the delegate's declared
  parameters bind the arguments by ordinal; six
  `corpus/p037-shapes/sidecar-delegate-*` shapes pin it, the 38 earlier shapes
  are byte-identical. Measured on the way (a §10.1 case-4 addition): the
  probe's coarse observation vocabulary could not see this step at all,
  because A' had already captured a delegate invocation on an owned parameter
  as a plain invocation of the delegate's `Invoke`; the vocabulary now
  distinguishes `sidecar_call`, `sidecar_call:object_creation` and
  `sidecar_call:delegate_invocation`, every column re-measured with the
  extractor of its step rebuilt at its commit (landed: `7de7a6f`, CI green);
- **A2.2-3P** the `guarded_functions[]` orphan carrier, production side
  (10.6.6): producer-validated, carried by both doors as additive unknown
  metadata, read by neither lowerer, no instrument change. A method enters the
  carrier only when it has guarded facts and no legacy `functions[]` record;
  one identity in both is a producer refusal; no dummy `functions[]` records.
  Landed in the commit carrying this line: the three legacy admission gates
  (no handle at all, every candidate escaped, an unmodelled construct) each
  hand the method to the carrier; the document's bytes are unchanged up to the
  appended carrier; the refusal is witnessed through the producer's own
  control knob; the inertness control now runs four variants (emitted,
  stripped, orphans_stripped, contradictory in both carriers) over the census,
  the relevance probe and the samples;
- **A2.2-4** completeness oracle plus generated hostile census: every
  occurrence is captured or matches exactly one named exclusion. Landed in the
  commit carrying this line (10.6.10): an independent Roslyn tool,
  `frontend/roslyn/OwnSharp.Oracle`, inventories every candidate occurrence by
  symbol, classifies it upward over syntax with Roslyn's conversions and
  ordinals, and joins both carriers by site identity; the generated census
  `corpus/p037-hostile` covers site form × value flow × binding × carrier
  admission pairwise plus the named compositions, the shadowing witnesses and
  the member kinds; every probe row and every hostile case reads as designed;
  five findings are classified and pinned RED by name in
  `corpus/p037-relevance/oracle_findings.json`, and NO production line moved;
- **A2.2-4R** the findings' repairs, each a separately classified change with
  its own census witness turning from pinned RED to green (10.6.10). Order
  ruled by the owner: R1 F-SHADOW, R2 F-PARAMS-ELEMENT, R3
  F-CONDITIONAL-RECEIVER (the three case-1 defects, same instrument, no new
  T/R between them), then R4 the F-VOCAB naming ruling, R5 the
  `constructor_initializer` call-like shape, R6 F-MEMBER through a
  guarded-only member enumeration. R1 landed in the commit carrying this
  line: the sidecar's handle and owned-parameter sets are symbol sets recorded
  at the legacy admission points beside the names, the legacy name-based
  structures untouched; the three shadowing witnesses read green, every other
  pinned RED stays, the 52 shapes and the probe are byte-identical. R2
  landed in the commit carrying this line: an expanded params element is
  classified from the ParamArray argument's array-initializer element, its
  element conversion included, so a handle under parentheses or `!` is no
  longer lost and a boxed or user-converted element no longer yields a false
  slot; the affected pairwise cases read green by the generic design. R3
  landed in the commit carrying this line: the reduced receiver of an
  invocation through a member binding (`r?.Ext(...)`) is read from the
  enclosing conditional access, so the handle binds declared ordinal 0 there
  too; `ext-conditional-access` reads green; the three case-1 findings are
  closed. R4 landed in the commit carrying this line, no production change:
  the registry, this section, the probe (three rows, their historical
  columns measured with each step's extractor rebuilt at its commit) and the
  oracle carry the three new exclusions; the constructor-initializer
  argument stays pinned RED under F-CTOR-INIT until R5. R5 landed in the
  commit carrying this line: `call_kind: constructor_initializer`, the
  initializer's argument syntax visited for nested call sites, the schema,
  the spec, the registry's call-like forms, a probe row (`CtorInit`, its
  historical columns measured with each step's rebuilt extractor and the
  whole probe re-measured into `a2_2_4r5_observed`), the census shape
  `sidecar-ctorinit-base` and three hostile witnesses; F-CTOR-INIT closes.
  R6 landed in the two commits carrying this line: R6a adds the two
  witnesses the ruling asked for (a default interface method with a body, a
  record struct method), pinned RED; R6b adds the independent guarded-only
  member enumeration feeding the orphan carrier, the legacy `functions[]`
  untouched, and every finding is closed: the oracle reads every input
  RED-free;
- **A2.2-5** mutation campaign, landed in the commit carrying this line
  (10.6.12): the control is itself put under test. Four frozen source
  metamorphs (remove the handle, add parentheses, perturb the binding in its
  named and its expanded-params form, distinguish nested calls) must stay
  green under contracts on the facts, five compile-valid reversions of the
  A2.2-4R repairs must be killed by exactly the RED the ledger pinned before
  each repair, and a taxonomy mutant (`predicate_result` removed from the
  registry) must read unclassified, never reclassified. A build failure, an
  extractor crash or an unrelated failure is a forbidden kill reason. Measured:
  5 metamorphs green, 5 producer mutants killed by their preregistered reason,
  1 taxonomy mutant unclassified, 0 survivors, 0 forbidden reasons;
- **A2.2-S** cumulative A2 after-evidence on M1 against the existing R with
  population T: fact shape MOVED as preregistered, MOS UNCHANGED, verdict
  UNCHANGED. The governed measurement is one command,
  `scripts/p037_cumulative_evidence.py` (10.6.13): the four takes verified and
  compared against R by the snapshot tools, every changed fact document
  classified by the allowed surfaces with unexpected changes 0, and an anchored
  per-document layer differential (lowered, summaries, verdicts, both engines,
  cross-engine agreement), fail-closed on the measurement head, the ancestry,
  the instrument identity and the baseline records. Landed in the commit
  carrying this line (10.6.13): the operator run on `P037_A2_MEASUREMENT_M1`
  against the reviewed orchestrator `e3995753b58c` gave `accepted=true`,
  `is_evidence=true`, `state=accepted`, every claim and every eligibility
  predicate true; evidence recorded at `f621400`;
- **A2.2-D** door registration: `guarded_facts` and `guarded_functions` become
  known, fail-loud vocabulary on both doors, still semantically inert; the
  instrument change, a new T/R round; phase B only after its evidence is green.

No new T/R is needed through A2.2-S, while the instrument stays the same and
the semantic doors do not read these facts. #263 is PARKED in parallel,
deliberately unmeasured, recorded on the issue.

#### 10.6.10 A2.2-4: the completeness oracle, what it is and what it found (REPOSITORY FACT)

The oracle is evidence infrastructure, deliberately not a second copy of the
production classifier (`frontend/roslyn/OwnSharp.Oracle/README.md`). Production
walks *downward* from an argument over Roslyn's operation tree; the oracle
walks *upward* from every local / parameter reference over syntax, asks Roslyn
for the semantic conversion at each edge (`GetConversion`) and for the declared
ordinal of each slot (`IArgumentOperation.Parameter`, reduced receivers at 0,
expanded params elements at the params ordinal), and joins the result with
`functions[].guarded_facts` and `guarded_functions[].guarded_facts` by call-site
identity (site line/column + ordinal), symbol for symbol. Its universe is
declared on symbols: owned parameters, `new`-created locals, first-party factory
locals, the `System.IO.File` factories and the two pool rentals; the legacy
pass's wider factory vocabulary is reported `outside_universe` by initializer,
never RED. Per universe occurrence it answers exactly one of *captured* (with
the representation the vocabulary owes), *excluded* (one of the frozen names,
eleven at the freeze and fourteen after the R4 ruling, attributed to the slot
it sits under; every call whose argument contains the
explained site is listed as an enclosing `nested_call_result`, so
`Use(Wrap(r))` reads inner-captured / outer-excluded), *not call-related* (a
closed table of named contexts) or RED. A derived value under an argument was
RED by the letter of the sentence, never a bin, until the R4 ruling named the
three it met (10.6.11). Every `var` / `param` fact must join an occurrence of the *same
symbol* at its site and ordinal, so a fact bound by spelling is RED.

It is held to a *designed* classification, not to production: the 32 probe
rows (28 at A2.2-4, the three exclusion rows of R4, the constructor row of R5)
read as their frozen class (recorded in `a2_2_4_oracle`, pinned by the
freeze test), and the generated census `corpus/p037-hostile` (142 cases: 114
pairwise over site form × value flow × binding × carrier admission, plus 28
named: the compositions, the shadowing witnesses, the member kinds, the
extension receivers, the vocabulary edges and the constructor initializers)
reads as `expected.json` designs it, occurrence by occurrence, carrier
included. The 55 A1.1/A2 census shapes (52 at A2.2-4, `sidecar-ctorinit-base`
of R5, the two `orphan-*` shapes of R6) and the repository's samples are
RED-free (samples: 163 universe occurrences, 25
captured, 120 excluded, 18 not call-related, 32 var/param facts all matched
by symbol).

Findings, classified by §10.1 and pinned RED by kind and count in
`corpus/p037-relevance/oracle_findings.json` (an unexpected RED fails CI; so
does a pinned RED that silently disappears):

| id | class | what | witness |
|---|---|---|---|
| F-MEMBER | 3 | expression-bodied members, struct, record, record struct and interface methods, property accessors were outside the legacy admission *and* the orphan carrier (the gates sit inside the class / block-body loop). **Repaired in A2.2-4R6** (10.6.11) | probe `Box.op_Implicit`; hostile `member-*`, now green |
| F-SHADOW | 1 | the guarded-fact handle set was keyed by spelling (`handles.Contains(lr.Local.Name)`) and the candidate collector descends into lambdas: a same-spelled non-candidate in a sibling scope, or beside a lambda-local creation, got a false `var` fact. **Repaired in A2.2-4R1** (10.6.11) | hostile `shadow-*`, now green |
| F-PARAMS-ELEMENT | 1 | an expanded params element was classified from its bare syntax: under parentheses or `!` the handle was lost (no operation of its own); under a boxing or user-defined element conversion a false opaque-and-relevant slot was emitted. **Repaired in A2.2-4R2** (10.6.11) | hostile `pw-*-params-*` with parens / bang / boxing / user_implicit, now green |
| F-CONDITIONAL-RECEIVER | 1 | `r?.Ext(...)` invokes through a member binding, the receiver was read from `MemberAccessExpressionSyntax` only, and ordinal 0 was dropped. **Repaired in A2.2-4R3** (10.6.11) | hostile `ext-conditional-access`, now green |
| F-VOCAB | 3 | four argument shapes the frozen list had no name for: a tested operand, an interpolation hole, an indexer argument, a constructor-initializer argument; production correctly emits nothing for the first three, the sentence demands a name. **Ruled in A2.2-4R4** (10.6.11): `predicate_result`, `interpolation_hole`, `indexer_argument` are frozen exclusions; the constructor-initializer argument is a call-like fact shape, F-CTOR-INIT, **landed in A2.2-4R5** | hostile `vocab-*`: all four green after R5 |

Two rulings the oracle reads into the freeze, recorded here as §10.1 case-4
clarifications rather than silently applied: `nested_call_result` is applied to
every inner call-like site of the vocabulary (an invocation, an object creation,
a delegate invocation) whose result is the outer argument, the registry's
"inner invocation" read through 10.6.2's non-propagation sentence and spec
§5.2's constructor paragraph; and `member_access_on_handle` is applied
wherever a member of the handle (a property, a field, an element, a chain)
reaches a call slot, an argument or a receiver alike. A2.2-4 changed no
production line: the three case-1 findings are repairs to be made one at a
time, each with its pinned witness turning green (A2.2-4R), and the two case-3
findings await a ruling.

**Owner rulings on the findings (recorded before R1).** F-VOCAB splits: a
tested operand becomes the named exclusion `predicate_result` (the handle
takes part in computing a predicate; the callee receives a bool), an
interpolation hole becomes `interpolation_hole` (the callee receives the built
string), an indexer argument becomes `indexer_argument`, whose definition must
say outright that the handle *is* semantically an argument of an accessor and
that indexer accessor calls deliberately stay outside the frozen call-site
vocabulary; a constructor-initializer argument is **not** an exclusion but a
call-like fact shape, `call_kind: constructor_initializer` (site the
`ConstructorInitializerSyntax`, callee the target constructor's `{Type}..ctor`
key, `sig` its canonical signature, arguments bound to the target
constructor's declared ordinals, `first_party` by declaring syntax, the same
value-flow and binding machinery), because `Holder(MemoryStream r) : base(r,
true)` is the same ownership edge `object_creation` was added for and "the
callee is outside the vocabulary" would be circular. The two case-4 readings
stand as recorded, `nested_call_result` reaching a constructor initializer
wherever such nesting is possible. F-MEMBER is a case-3 production
completeness repair, not a perpetual gap, under one boundary: the legacy
`functions[]` universe does not grow; an independent guarded-member
enumeration over every supported type and member body feeds
`BuildGuardedFacts` and the orphan carrier when no legacy record exists, with
two more witnesses (a default interface method with a body, a record struct
method) added before it closes; lambdas and local functions stay the separate
nested-function gap.

#### 10.6.11 A2.2-4R: the repairs (REPOSITORY FACT)

- **R1, F-SHADOW.** `BuildGuardedFacts` now takes `HashSet<ISymbol>` handle
  and owned-parameter sets (`SymbolEqualityComparer.Default`). They are filled
  at the legacy admission points, beside the names the legacy path keeps
  reading (`Admit(v)` records `GetDeclaredSymbol(v)` next to
  `candidates.Add(v.Identifier.Text)`; the owned-parameter loop records the
  parameter symbol next to its name), so which declarator was admitted is
  known by identity rather than re-derived from a spelling. `ParamFact` tests
  `ownedParams.Contains(p)` and the local-reference case tests
  `handles.Contains(lr.Local)`. No legacy structure, escape rule, tracking set
  or lowering input changes. Measured: the 52 census shapes and the probe's
  facts are byte-identical; the three shadowing witnesses read green
  (`shadow-lambda-local` now has no fact and no carrier, the truth); every
  other pinned RED stays; inertness and the local rehearsal unchanged.
- **R2, F-PARAMS-ELEMENT.** In `EmitCall.ValueOf`, when no argument operation
  is attached to the argument's span, the expanded params element is looked
  up in the ParamArray argument's `IArrayCreationOperation` initializer (the
  element whose syntax the argument contains) before falling back to
  `GetOperation` on the bare expression. The element carries its own
  conversion, so the existing walker decides it: `(r)` and `r!` yield the
  local reference (a handle, `opaque` in the params slot, relevant), a struct
  handle into `params object[]` yields a boxing conversion (not a handle) and
  a handle into `params Box[]` a user-defined one (not a handle). The
  collapsed form (an array passed whole) matched by span before and still
  does. Measured: the 52 shapes and the probe byte-identical; the four
  affected pairwise compositions (parens, bang, boxing, user_implicit under an
  expanded params binding, across site forms and carriers) read green by the
  generic design; every other pinned RED stays; inertness and the local
  rehearsal unchanged.
- **R3, F-CONDITIONAL-RECEIVER.** In the invocation loop the reduced
  receiver is read from a `MemberAccessExpressionSyntax` as before and, for
  an invocation whose expression is a `MemberBindingExpressionSyntax`, from
  the nearest enclosing `ConditionalAccessExpressionSyntax`'s expression: a
  binding is by construction the first operation after its `?.`, so that
  expression is the receiver (`a?.B?.Ext()` reads the inner binding `.B`, a
  member, not a handle). The receiver then goes through `ValueOf` and the
  walker as a member-access receiver does, with one more rule in the walker:
  Roslyn binds such a receiver argument to an
  `IConditionalAccessInstanceOperation` placeholder, which stands for the
  conditional access's own operand (the same reference when the call is
  entered at all; a null operand skips the call and yields no alternate
  value), so the walker classifies that operand. Measured: the 52 shapes
  and the probe byte-identical; `ext-conditional-access` reads green
  (captured, ordinal 0, `var`); every other pinned RED stays; inertness and
  the local rehearsal unchanged.
- **R4, the F-VOCAB ruling.** No production line moves. Three exclusions
  join the registry with definitions and probe rows: `predicate_result`
  (`PredicateResult`: `Use6(r != null)`), `interpolation_hole`
  (`InterpolationHole`: `Use4($"{r}")`), `indexer_argument`
  (`IndexerArgument`: `d[r] = 1`, whose definition states that the handle is
  an argument of an indexer accessor's call and that such calls deliberately
  stay outside the frozen call-site vocabulary). The three rows' historical
  columns were measured with the extractor rebuilt at A' (`5a0de070`),
  A2.2-1 (`268bbd4`), A2.2-2 (`376f2e6`), A2.2-2b (`7de7a6f`) and A2.2-3P
  (`80cd9aa`): `record_without_call_fact` for the first two at every step
  (the handle never escapes, the method is admitted, no call fact), `no_record`
  for the third (the index position is an argument to the legacy escape rule,
  every candidate escapes, no fact exists to carry). The oracle assigns the
  three names (a tested operand or an interpolation hole *under an argument*;
  any element-access index), and its RED kinds shrink to the constructor
  initializer, which the same ruling re-classifies as a call-like fact shape:
  `Holder(MemoryStream r) : base(r, true)` is the ownership edge
  `object_creation` was added for, so it earns `call_kind:
  constructor_initializer` in R5 and stays pinned RED under F-CTOR-INIT until
  then. The three `vocab-*` witnesses read green by their designs.
- **R5, `constructor_initializer`.** `BuildGuardedFacts` emits one call fact
  for a constructor's `: this(...)` / `: base(...)` through the shared
  `EmitCall`: the site is the `ConstructorInitializerSyntax` (its coordinate
  the `:`), the callee the target constructor's `{Type}..ctor` key with its
  canonical signature, `first_party` by declaring syntax, the arguments bound
  to the target constructor's declared ordinals (named arguments resolved,
  the params and ref/out rules as everywhere), `form` `statement` (it runs
  first and yields nothing), `call_kind: constructor_initializer` (schema
  enum, producer set and spec §5.2 in step). The initializer sits beside the
  body, so the invocation and object-creation loops now walk the
  initializer's argument syntax before the body's: `: base(Wrap(r), true)`
  captures `r` at `Wrap` and the initializer receives a call result, the
  nested_call_result reading the R4 ruling asked for. Measured: the 52 shapes
  and every earlier probe row byte-identical (`a2_2_4r5_observed` equals
  `a2_2_3p_observed` on all 31 of them); the new row `CtorInit` reads
  `orphan_call:constructor_initializer` (an empty forwarding body lowers to
  nothing, so the legacy pass admits no record and the carrier holds the
  fact; `no_record` at every earlier step, measured with each step's rebuilt
  extractor); the census shape `sidecar-ctorinit-base` and the three
  `ctorinit-*` / `vocab-constructor-initializer` witnesses read green; the
  oracle's `unclassified_argument_shape` kinds are empty over every input;
  inertness and the local rehearsal unchanged.
- **R6, F-MEMBER.** R6a first pins two more witnesses RED, because the root
  cause is the enumeration and not struct-ness: a default interface method
  with a body and a record struct method. R6b then adds `GuardedOnlyMembers`,
  an independent walk over every `TypeDeclarationSyntax` that yields exactly
  the bodies the legacy loop does not read (an expression-bodied method-like
  member of a class; every method-like member of a struct, record, record
  struct or interface; every accessor with a body; an expression-bodied
  property or indexer, its getter), run after each tree's legacy class loop
  so every earlier orphan keeps its place. `GuardedOnlyAdmission` records,
  as symbols, the same owned-parameter predicate and the same candidate
  families in the same order as the legacy loop admits for its own methods;
  `BuildGuardedFacts` takes any member declaration and any body, a block or
  an arrow clause; the result rides in `guarded_functions[]`. The boundary
  ruled for it holds by construction: no legacy structure, gate or lowering
  input changes, and no member enumerated here ever had a `functions[]`
  record, so the carrier's identity refusal cannot fire. Lambdas and local
  functions stay the separate nested-function gap. Measured: the 53 census
  shapes byte-identical and two new shapes (`orphan-expression-bodied`,
  `orphan-struct-method`) pin the repair; the probe re-measured into
  `a2_2_4r6_observed` moves no row while its helper `Box.op_Implicit` now
  carries its `object_creation` fact as an orphan; the six `member-*`
  witnesses read green with carrier `guarded_functions`; the oracle raises
  no RED over any input, the ledger's `expected_red` is empty and F-MEMBER
  moves to `closed`; inertness and the local rehearsal unchanged. With R6
  every A2.2-4 finding is either repaired or a consciously frozen named
  exclusion: the completeness phase's goal, not merely "we know where the
  red is".

#### 10.6.12 A2.2-5: the mutation campaign (REPOSITORY FACT)

After A2.2-4R every finding is repaired or consciously frozen, and the only
question left about the completeness control is whether it can still catch
what it once caught, and whether it reads a call site by meaning rather than by
spelling. A2.2-5 answers both with a campaign the tree carries
(`scripts/p037_mutation_campaign.py`, `corpus/p037-mutation`: a generated
manifest, the base programs, and a deterministic `report.json` recorded for one
manifest digest and one production digest; `tests/test_p037_mutation_campaign.py`
holds the three to each other without dotnet, and the campaign itself runs in
CI beside the oracle and must reproduce the record).

The rule comes first, because a mutation campaign without it proves nothing: a
mutant is **killed** only when it stays valid C#, the extractor runs to
completion, and the oracle or the frozen-vocabulary infrastructure raises
exactly the RED / mismatch preregistered for it. A build failure, a compile
error, an extractor crash, an oracle crash or an unrelated check failing is a
**forbidden kill reason**, fails the whole campaign and never counts as a catch.
Three surfaces:

- **Source metamorphs** (expected green). A base program and one frozen
  rewrite, each run through the extractor and the oracle, held to its own
  designed classification and then to a contract on the facts. REMOVE_HANDLE
  (`Sink(r, true)` → `Sink(Stream.Null, true); r.Dispose();`): the record stays
  in `functions[]`, the `Sink` fact (`var r` at ordinal 0, the `true` literal
  as `bool_const` at ordinal 1) disappears, no stale `var(r)` anywhere.
  ADD_PARENTHESES (`Sink((((r))), true)`): the fact is equal modulo its source
  coordinate and the oracle's occurrence is equal (same symbol, ordinal 0,
  `var`, invocation). PERTURB_BINDING (`Take(first: r, second: q)` →
  `Take(second: r, first: q)`): `r` moves to ordinal 1 and `q` to ordinal 0 by
  declared parameter; its expanded-params twin (`TakeP(r, q)` → `TakeP(q, r)`
  against `TakeP(Stream first, params Stream[] rest)`): `q` becomes the `var`
  at ordinal 0 and `r` the opaque params slot at ordinal 1, the R2 machinery
  under perturbation. DISTINGUISH_NESTED (`Use(r)` → `Use(Wrap(r))`): the inner
  `Wrap` captures `var r` at ordinal 0, the outer occurrence reads
  `nested_call_result`, no fact at `Use` carries `var(r)`. Measured: all five
  green, every obligation met; the one obligation that failed on the first run
  was the contract's, not production's (it had named ordinal 0 alone where the
  fact truthfully also carries the `true` literal), and was completed.
- **Producer regression mutants** (expected killed). Five compile-valid
  reversions of the A2.2-4R repairs, each an exact `find` / `replace` on the
  extractor whose anchor must occur exactly once, applied to a *copy* of the
  project in a temporary directory and built there (the production tree is
  never written; digests and `git status` before and after are part of the
  record). Each runs over the inputs it names and must raise exactly the RED
  map pinned before the repair: K-SHADOW (handle lookup by spelling again)
  `fact_binds_other_symbol` on the three `shadow-*` witnesses; K-PARAMS (no
  ParamArray-element recovery) `occurrence_not_captured` under parentheses and
  `!`, `fact_without_relevant_occurrence` under boxing and `op_Implicit`, the
  four cases the A2.2-4 ledger pinned; K-COND-RECV (no MemberBinding receiver)
  `occurrence_not_captured` on `ext-conditional-access`; K-CTORINIT (no
  `constructor_initializer` fact) `occurrence_not_captured` on two hostile
  witnesses, the probe row `CtorInit` and the shape `sidecar-ctorinit-base`,
  while `ctorinit-nested-call` stays green because the initializer's nested
  calls are still walked; K-MEMBER (the guarded-only enumeration restricted to
  class members with a block body, the legacy loop's own domain)
  `occurrence_not_captured` on the six `member-*` witnesses, the probe helper
  `Box.op_Implicit` and the two `orphan-*` shapes. Measured: all five killed,
  each by exactly its preregistered map, nothing else red on any input.
- **A taxonomy contract mutant** (expected unclassified). `predicate_result`
  removed from a copy of the registry: the freeze test fails exactly
  `classification-valid` ("unknown exclusion 'predicate_result'") and
  `registry-non-vacuous`, the hostile-census test exactly
  `designs-use-frozen-vocabulary` ("not frozen"), and the oracle driver's
  check `oracle-exclusions-frozen[*]`, added for this, exactly on the probe and
  the hostile census ("names the registry does not freeze: unclassified, not a
  bin"), while the shape keeps its occurrences (the probe row `PredicateResult`
  read `excluded:predicate_result` before the removal). Nothing folds the shape
  into a neighbouring name; a future `other_expression` bucket dies here.

Acceptance is the whole list or nothing: every declared mutant exercised
exactly once, every C# mutant compiles, every metamorph green, every producer
mutant killed by its preregistered reason, the taxonomy mutant unclassified, no
survivor, no unexpected kill reason, the production tree byte-identical
afterwards, the ordinary oracle RED-free on every campaign input, no open
finding. Measured on the tree at the A2.2-4R-fix commit: 11 mutants, 5 green,
5 killed, 1 unclassified, 0 survivors, 0 forbidden reasons, about a hundred
seconds. What the campaign does not claim: it proves the control catches the
six defects it once found and reads four rewrites by meaning; it does not
enumerate the extractor's other seams, the hostile census remains pairwise, and
lambdas / local functions stay the separate nested-function gap. After A2.2-5
no functionality is added: A2.2-S measures the whole of A2 once against T/R.

#### 10.6.13 A2.2-S: the governed cumulative measurement (REPOSITORY FACT)

A2 is one treatment with one preregistered cause of FACT-DIFF, the guarded-fact
sidecar and its orphan carrier, and one obligation: richer facts, zero MOS and
zero verdict movement, on both engines. Every A2.2 step rehearsed that locally;
A2.2-S measures it once, cumulatively, against the baseline evidence R recorded
at T on the measurement machine (10.6.0). The population is T
(`4a8e6582e10222403cd40adc9e95db7e0228a1c2`), the baseline evidence R
(`5fd6bfa6abd4c2af7e53712af300cf66c97f2f50`, the four `p037-a2-baseline-*`
records under `docs/evidence`), the treatment the A2.2-5 head
(`dab3db19c4611c116f37f2b0e49354a0fd9bf384`). The measurement is one command,
`scripts/p037_cumulative_evidence.py run`, evidence orchestration over the
existing instrument and deliberately not part of the frozen instrument closure
(registering it there would move `instrument_paths` under every record R
carries): it calls the snapshot tools of the measured checkout, imports that
checkout's own `p037_evidence` / `shadow_compare` / `ownlang.repro`, and adds
nothing the instrument does not already do.

Three claims, proven together in one artifact (`p037-a2.2-s-cumulative.json`
and its manifest), or refused:

- **FACTS MOVED**, and only where allowed. For every MOS document (the 137
  corpus programs one at a time, the repository tree as one compilation) the
  baseline facts are re-derived by the extractor built from T's own sources in
  a temporary worktree, run in the measured checkout root, and accepted only
  when their digest equals the one R's record carries for that document; the
  treatment facts are re-derived by the tree under test and accepted only when
  their digest equals the fresh take's. Each anchored pair is diffed
  structurally and every difference is classified by path: an added or changed
  `functions[i].guarded_facts` and the top-level `guarded_functions[]` carrier
  are the allowed surfaces; a changed legacy body, signature, `services`,
  `components`, `stats`, `ownir_version`, a function added or removed, or any
  other new top-level key is UNEXPECTED and refuses the claim (the selftest
  pins each of these controls). A document that cannot be anchored refuses the
  differential; nothing is inferred from a digest that did not match.
- **MOS UNCHANGED.** The two MOS takes (`mos-repo`, `mos-corpus`) are taken at
  the treatment with population T, verified fresh at the treatment and
  compared against R by `p037_mos_snapshot.py compare` (whole summaries
  document per engine, cross-engine parity on the after side); in addition the
  anchored pairs go through both engines' capture (the P-022 envelope) and the
  `summaries` layer of every document is digested on both sides, per engine.
- **VERDICTS UNCHANGED.** The two verdict takes are compared against R at
  level `verdict` and at level `all` (advisories included), the after-side
  Python and Rust snapshots are compared file by file (finding sets and exit
  codes), and the `verdicts` layer of every anchored pair is digested per
  engine. The `lowered` layer rides along on the same terms, so the matrix the
  artifact carries is engines × {lowered, summaries, verdicts} mismatches, plus
  Python/Rust disagreements per layer on both sides.

Provenance is fail-closed, before anything runs: the measured checkout's HEAD
must be exactly the named treatment (a descendant is not the treatment, even a
docs-only one), the tree clean before and after, T an ancestor of R and R of
the treatment, the instrument closure's object ids identical at T, R and the
treatment (recorded as the instrument identity, next to the qualified
`own-cli` / `own-shadow-engine` digests the takes ran), the four baseline
records the very files committed at R (their digests pinned by R's manifest
and their blobs by R's tree), every take fresh at the treatment with
`source_commit` equal to it, every comparison eligible by the snapshot tools'
own rules (same population, same support closure, same execution profile,
before an ancestor of after), every document anchored, the own-shadow-engine
built for the differential byte-identical to the one the MOS takes executed.
Any failure stops the run with `REFUSED` and nothing is written as evidence;
`--mode rehearsal` produces the same artifact against a same-machine T
baseline with `is_evidence=false`, which is how the procedure is exercised
where the execution profile is not M1's. The evidence run itself is the
operator's, on `P037_A2_MEASUREMENT_M1`, with the workspace checkout at the
treatment and `--out` outside it; its outputs (the four after-takes, the
cumulative artifact, the manifest) land in `docs/evidence` as an evidence-only
commit, exactly as R and S' did.

**Rehearsed here, before the operator run (REPOSITORY FACT, not evidence).**
The whole procedure was exercised on this machine the way M1 will run it: a
dedicated checkout at T took the four before-takes with population T (the
same-machine stand-in for R; its 137 corpus facts digests equal R's byte for
byte, its repo-tree digest differs from R's only by the #364 absolute paths of
another checkout root), the checkout moved to the treatment, and the driver
ran in `--mode rehearsal` against those takes. Measured: preflight green
(head = treatment, instrument object ids identical at T, R and the treatment,
baseline records pinned); four takes fresh at the treatment and all four
compares UNCHANGED (mos-repo facts_moved=1, mos-corpus facts_moved=46,
python_mos_moved = rust_mos_moved = after_parity_moved = 0; verdict-python and
verdict-rust no verdict moved at level verdict and at level all, 137 files);
138 documents anchored, 47 changed and 91 unchanged, every changed document
classified `moved_allowed` (86 functions gained `guarded_facts`, 21 orphan
records in `guarded_functions[]`), unexpected 0; the layer matrix all zeros
(Python and Rust × lowered, summaries, verdicts), Python/Rust disagreements 0
on both sides, verdict-snapshot cross-engine disagreements 0; the tree clean
afterwards; about twenty-nine minutes. FACTS MOVED, MOS UNCHANGED, VERDICTS
UNCHANGED, `accepted=true`, `is_evidence=false` by mode. The one predicate
that failed on the first render was the driver's own, not the measurement's
(it compared whole execution profiles across the four takes, and a
Python-only verdict take records no Rust identity by design); it now compares
the identities each take carries, the selftest pins the rule, and the artifact
was re-rendered from the persisted measurement (`--stage report`) with every
measurement block byte-identical. The 46 corpus documents against S''s 36 are
the cumulative A2.2 treatment (transparent wrappers, the call-like forms, the
orphan carrier, the guarded-only members) reaching more programs than A2.1
did; every one of them moves inside the allowed surfaces only.

The evidence run on M1 is the operator's: with the workspace checkout clean
at `dab3db19c4611c116f37f2b0e49354a0fd9bf384`, the driver taken from the
commit carrying this section (it is not in the treatment tree, and imports
the measured checkout's own instrument), `--out` outside the checkout:

    python3 <tooling checkout>/scripts/p037_cumulative_evidence.py run \
        --repo <M1 workspace checkout> \
        --treatment dab3db19c4611c116f37f2b0e49354a0fd9bf384 \
        --population 4a8e6582e10222403cd40adc9e95db7e0228a1c2 \
        --baseline-commit 5fd6bfa6abd4c2af7e53712af300cf66c97f2f50 \
        --orchestrator-commit <the tooling commit the driver is checked out from> \
        --out <directory that does not exist yet, outside the checkout>

S is accepted when the artifact says `accepted=true`, `is_evidence=true`, and
its outputs land in `docs/evidence` as `p037-a2.2-s-*` in an evidence-only
commit. Then the A2 treatment is finished; A2.2-D (door registration, a new
T/R round) is the next and only step before Phase B.

**Orchestration hardening before the operator run (OWNER REVIEW, landed in
the commit carrying this paragraph; driver, tests and docs only, the
treatment, T, R and the instrument closure byte-identical).** Review of the
driver found three provenance holes in the orchestration, cheap to close
before a half-hour M1 run and expensive after: (H1) "one command" was prose,
not a rule, since `--mode evidence` accepted `--stage takes|layers|report`
and evidence could have been assembled by three processes under another
protocol; now evidence refuses any `--stage` (staging is for rehearsal and
debugging); (H2) "nothing is written as evidence" was technically false, since
a late `REFUSED` left the four after-takes (each `is_evidence=true` on its
own), `takes.json` and `layers.json` behind under a final-looking `--out`,
half a failed S that somebody would eventually commit; now evidence output is
a transaction: `--out` must not exist, everything runs in a sibling staging
directory, a `REFUSED` deletes it and the final `--out` never comes to exist,
a valid negative result (a real movement, `accepted=false`) is published in
full with exit 1 because negative evidence is evidence, and an accepted
result is published with exit 0; (H3) the driver recorded its own path and
sha256, which says what ran but not that it was the reviewed tooling; now the
driver must run from a clean git checkout and be byte-identical to the blob at
that checkout's HEAD, refused otherwise, and the artifact records the
orchestrator as commit, blob and sha256, so the evidence names three
identities separately: the treatment (`dab3db1`), the frozen instrument
closure (T/R's object ids), the evidence orchestrator (the reviewed tooling
commit); (H4) `bootstrap` proved the path of `p037_evidence` only; now every
measurement module (`p037_evidence`, `p037_mos_snapshot`,
`p037_verdict_snapshot`, `shadow_compare`, `ownlang`, `ownlang.repro`) is
purged from the module cache, imported with the measured checkout first on
`sys.path`, and refused unless its file resolves to the measured checkout's
own, by path. The selftest pins the controls: evidence with a stage refused;
a pre-existing `--out` refused; a simulated late `REFUSED` after a written
take leaves neither a final `--out` nor a staging directory; a valid negative
result published with exit 1; a clean reviewed driver accepted, a modified
driver, a dirty driver checkout and a loose copy outside any checkout
refused; the measured checkout's modules accepted, a foreign module path and
a missing module refused. Exercised end to end on this machine: an evidence
run against `docs/evidence` reaches the first comparison, is refused there by
the instrument's own rule (this machine's execution profile is not M1's) after
a real take had been written, and leaves nothing behind. The operator
command in the paragraph above is unchanged; the driver is now taken from a
clean checkout of the tooling commit rather than copied.

**Second review, before the operator run (OWNER REVIEW, landed in the commit
carrying this paragraph; again driver, tests and docs only).** Reading the
driver against its own contract found three more holes, two of them
contradicting H2 and H3 as claimed. (H3') "reviewed tooling" was a
convention: the pin proved a clean checkout and a blob equal to its HEAD, but
any commit's HEAD, and the selftest even accepted a throwaway repository as a
reviewed driver. Evidence mode now requires `--orchestrator-commit <full
SHA>` and refuses unless the driver's checkout HEAD is exactly that commit
(the SHA is an argument, never hardcoded into the commit that would change
it); the artifact records `pinned_to`. (H4') the trust chain was reversed:
`bootstrap` imported the measured checkout's `p037_evidence`,
`p037_mos_snapshot`, `p037_verdict_snapshot`, `shadow_compare`, `ownlang` and
`ownlang.repro` before anything had proven the checkout clean and at the
treatment, and the preflight then ran through those very modules. The driver
now authenticates the measured checkout with git alone, before the first
import: `--repo` is a checkout root, HEAD equals the treatment, the tree is
clean, and each of the six module files on disk hashes to its blob at the
treatment; only then are the modules imported and proven by path, and only
then does the instrument-level preflight run through them. (H2') the protocol
had two states where it promised three: eligibility predicates (an unanchored
document, a dirty tree after the run, inconsistent execution profiles) sat in
the same `conditions` map as the scientific claims, so a measurement that
could not honestly be made was published as `accepted=false`, and a valid
negative result carried `is_evidence=false`, indistinguishable from a
rehearsal by that field. The artifact now separates `eligibility` (head,
instrument, the pinned orchestrator, the authenticated checkout, four takes
fresh and evidence, four comparisons eligible, every document anchored, one
execution profile, tree clean after) from `claims` (facts moved, unexpected
zero, MOS and verdicts unchanged on both engines, engines agree, the layer
matrix zero): any eligibility failure is `REFUSED` and nothing is published;
`is_evidence` is true for every published evidence-mode artifact; `accepted`
is the claim, and `state` reads `accepted`, `negative_evidence` or
`rehearsal`. An unanchored document also refuses inside the differential
itself, and a take that does not mark itself evidence refuses the run. (P2)
the publishing rename sits inside the transaction's cleanup: a failed rename
removes the staging directory and refuses. Controls added to the selftest: an
orchestrator-commit mismatch or a short SHA refused, a match accepted; a
clean checkout at the treatment authenticated, another head, a non-root
`--repo`, a module tampered before import and a dirty tree refused; a failed
publish rename refused with no staging left; a valid measurement whose claim
holds accepted with `is_evidence=true`, whose claim fails published as
negative evidence with `is_evidence=true`, while a dirty tree after the run,
an unanchored document, mismatched profiles and an unpinned orchestrator are
refused, and a rehearsal is never evidence. The operator command gains
`--orchestrator-commit` naming the tooling commit the driver is checked out
from; everything else, the treatment, T, R and the instrument closure, is
byte-identical.

**The operator run (REPOSITORY FACT).** Four names, kept apart: **T** =
`4a8e6582e10222403cd40adc9e95db7e0228a1c2` (the frozen population); **R** =
`5fd6bfa6abd4c2af7e53712af300cf66c97f2f50` (the baseline evidence recorded at
T); the **treatment** = `dab3db19c4611c116f37f2b0e49354a0fd9bf384` (A2.2-5,
the tree this section measures); the **evidence orchestrator** =
`e3995753b58cfc2c6b48b712963df6c51c79af66` (`scripts/p037_cumulative_evidence.py`,
tooling branch `claude/p037-a2.2`, byte-identical to its branch tip, pinned by
`--orchestrator-commit`, never edited to obtain this result); the **S
evidence-only commit** = `f6214004f38258ef1bb2244d38552f233bc3f214`, carrying
the six files this section quotes verbatim from.

The run executed on the preserved M1 measurement machine (`P037_A2_MEASUREMENT_M1`,
the same machine and toolchain pins that produced R and the A2.1 after-evidence),
from a tooling checkout independent of the measured checkout, in `--mode evidence`
(no `--stage`). Provenance, read from `p037-a2.2-s-cumulative.json`, all true:
the orchestrator is clean and byte-identical to its pinned commit; the measured
checkout's HEAD is exactly the treatment and was authenticated against the
instrument's module blobs before any import; the instrument (`ownlang/`,
`rust/`, `scripts/own-check.sh`, `scripts/p037_evidence.py`,
`scripts/p037_mos_snapshot.py`, `scripts/p037_verdict_snapshot.py`,
`scripts/shadow_compare.py`) is object-identical at T, at R and at the
treatment; every one of the four governed takes is fresh evidence and every
compare against R is eligible; every one of the 138 fact documents anchored
(zero `anchors_failed`); the execution profile is single across the whole run;
the tree is clean after. Two prior attempts on this same machine did not reach
a result and are not this record: the first hung indefinitely inside the
extractor (a dotnet child stuck in `futex_do_wait`, zero CPU consumed across
40+ minutes, traced afterward to the pinned `.NET SDK` directory having gone
missing from disk mid-run) and was killed rather than left to silently retry;
the second, after the SDK was restored byte-for-byte from the untouched
provisioning recipe and re-verified against R's execution profile, was
REFUSED cleanly by the orchestrator's own eligibility check (`before/after
execution profiles differ`) because the ambient `dotnet` on `PATH` had
silently substituted an unpinned system installation once the pinned one was
gone — a real provenance failure, correctly caught, nothing published. This
record is the third attempt, run only after the pinned SDK was confirmed
byte-identical to R's execution profile.

Result: `state=accepted`, `accepted=true`, `is_evidence=true`. All six claims
true — `facts_moved`, `mos_unchanged_both_engines`,
`verdicts_unchanged_both_engines`, `unexpected_fact_changes_zero`,
`layer_engines_agree`, `verdict_engines_agree` — and all nine eligibility
predicates true. 138 fact documents measured (1 `repo-tree` document over the
81-file repo population, 137 individual corpus documents): 47 changed (1 from
`repo-tree`, 46 from the corpus), 91 unchanged, 0 unexpected — every one of
the 47 changes classified as confined to `functions[*].guarded_facts` and the
`guarded_functions[]` carrier, none touching a legacy body, a signature,
`services`, `components`, `stats` or the schema version. The governed takes
against R: MOS repo `UNCHANGED` (`facts_moved=1`, `python_mos_moved=0`,
`rust_mos_moved=0`, `after_parity_moved=0`); MOS corpus `UNCHANGED`
(`facts_moved=46`, `python_mos_moved=0`, `rust_mos_moved=0`,
`after_parity_moved=0`); verdict/python `UNCHANGED` at both `level=verdict`
and `level=all` over 137 files; verdict/rust `UNCHANGED` at both levels over
137 files, its `own-cli` qualified/executed sha256 equal and
`post_run_intact=true`. The layer differential (per-document digests, both
engines, anchored against T's own re-derived facts and the treatment's):
Python mismatches `{lowered: 0, summaries: 0, verdicts: 0}`; Rust mismatches
`{lowered: 0, summaries: 0, verdicts: 0}`; Python/Rust cross-engine
disagreements at the treatment `{lowered: 0, summaries: 0, verdicts: 0}` (and
at the baseline, independently, the same all-zero); verdict-snapshot
cross-engine disagreements over the 137 corpus files `{verdict: 0, all: 0,
exit: 0}`. Aggregated over the 47 changed documents, the same 86 functions
gained `guarded_facts` and the same 21 orphan records reached
`guarded_functions[]` as the rehearsal above measured: the operator run and
the rehearsal agree on every count.

A2 treatment is closed by this measurement: the sidecar's fact surface moved
exactly where A2.2 licensed it to, MOS and verdicts on both engines did not
move at all, and the two engines agree with each other and with themselves
before and after. Nothing here reads `guarded_facts` or `guarded_functions[]`
into a verdict; that is A2.2-D's own instrument epoch, not this one's claim.

#### 10.6.14 A2.2-D: the door-registration epoch, frozen before implementation (OWNER RULING)

A2.2-S closed the a2 instrument epoch: population T `4a8e658`, baseline R
`5fd6bfa`, the corrected A2.1 treatment A' `5a0de07` with its after-evidence S'
`cd7e020` and the merge `23e3203`, the A2 treatment head `dab3db1`, the S
evidence `f621400` (`state=accepted`, `is_evidence=true`) and its landing
`fa92c05`, the reviewed orchestrator `e399575`, the integration head `6f9c373`.
Every one of them is a historical predecessor of what follows and none is a
baseline, a before side or a control of it: A2.2-D changes the measurement
instrument, so R is by definition not a baseline of the new instrument, and
`P037_A2_MEASUREMENT_M1` retires with the epoch. Nothing of the old epoch is
retaken, edited or revalidated. The machine-readable form of this section is
`docs/evidence/p037-a2d-epoch.json`; `tests/test_p037_a2d_epoch.py` holds the
record, this section and the tree to each other, and enforces the order below
with git: until the R_D manifest names T_D, no door may move on this branch.

**What A2.2-D is.** Both OwnIR doors register `guarded_facts` (on a
`functions[]` record) and `guarded_functions[]` (the top-level orphan carrier)
as KNOWN, fail-loud vocabulary, validated at load against spec §5.2 and §5.3
with the same refusal categories on both engines (the Python door is
`ownlang/ownir.py::load`, which today reads neither key; the Rust door is
`rust/crates/own-ir/`, whose strict validator mirrors the Python reference and
whose model carries every undeclared field in a flattened `extra` map), while
every lowerer, summary and verdict stays silent about them. A sidecar outside
the vocabulary is refused at both doors; a valid sidecar is accepted and
preserved unchanged; a valid contradictory sidecar still moves no layer (the
inertness control of A2.1 extended to both refusals and preservation).

**The a2d closure.** Treatment, the paths that may move during the D
treatment: `ownlang/ownir.py`, `rust/crates/own-ir/`, `spec/`: the smallest
git-addressable units that contain the two doors today (the Python door lives
in the same file as the Python lowering; a D treatment diff inside these units
is bounded mechanically by the production-diff gate of the tightening below,
not by review), and the vocabulary text. Instrument, frozen for the epoch and identical at T_D,
R_D and every after head: `frontend/roslyn/OwnSharp.Extractor/` (the sidecar's
producer joins the instrument in this epoch), `ownlang/` and `rust/` minus the
two carve-outs, `scripts/own-check.sh`, `scripts/p037_evidence.py`,
`scripts/p037_mos_snapshot.py`, `scripts/p037_verdict_snapshot.py`,
`scripts/shadow_compare.py`. Nothing the a2 closure measured falls out of the
a2d closure; it moves from one side to the other only. The orchestrator
`scripts/p037_cumulative_evidence.py` stays outside the closure, pinned per run
to a reviewed commit by `--orchestrator-commit` from a clean checkout.

**The environment.** `P037_A2D_MEASUREMENT_M2`, qualified before R_D: an
isolated pinned toolchain (CPython, .NET SDK, rustc/cargo) provisioned by a
recipe whose sha256 the R_D manifest records and that is retained outside the
repository, as M1's was; the execution profile captured before R_D and equal
on every record of the epoch, a differing profile ineligible; one measured
workspace checkout root for T_D, R_D and every after run (the path-sensitive
`scope_cache_sites[].file`, #364, is still there); the environment id recorded
on every record of the epoch and required equal by every comparison, so an a2
record, which carries none, is ineligible by construction. M1 takes nothing
for this epoch and is not a control of M2; changing the machine at an epoch
boundary costs nothing methodologically, changing it inside one would.

**Order and gates.** (1) freeze: this section and the record, docs only, no
implementation. (2) tooling: `p037_evidence.py` learns the a2d closure (roots
minus carve-outs), records the epoch and the environment id (taken from the
record, never from an operator string) on every take and refuses a cross-epoch
or cross-environment comparison; the cumulative driver reads the preregistered
fact expectation from the record's closed field `measurement_policy.fact_diff`
and applies the production-diff gate to the treatment head as eligibility; CI
green; no door, extractor or spec line moves. (3) T_D: a terminal-green
descendant of `6f9c373`, the freeze and the tooling, whose doors are
byte-identical to `6f9c373`'s (gate verdict IDENTICAL), named by the R_D
manifest, never by the record. (4) R_D: the four governed baseline takes at
T_D on M2, verified fresh at T_D, an evidence-only commit whose manifest names
T_D, the environment id, the profile and the recipe sha256. (5) the D
treatment: the door registration on both doors with its validation-ledger
controls and the extended inertness control; only the treatment paths and
tests move, and only within the production-diff gate against T_D. (6) D after: the governed cumulative measurement at the D head
against R_D on M2 by the pinned orchestrator. Preregistered claims: FACTS
UNCHANGED on every document (the extractor is instrument now, a moved fact
document is a failed claim, never a licensed movement), MOS UNCHANGED and
VERDICTS UNCHANGED on both engines at both levels, the engines in agreement
on lowered, summaries and verdicts before and after, and the fail-loud
controls green. The population of a2d is re-frozen at T_D (the tracked `.cs`
under the corpus and repo-tree roots at T_D; the repo tree now includes
`frontend/roslyn/OwnSharp.Oracle/Program.cs`) and is not compared with T's.
Phase B, where the lowerers begin to read the guarded facts, is an instrument
change again and opens an epoch of its own after D's evidence is green.

**Freeze tightening (OWNER RULING).** The freeze as first written left two
places where "we agreed" stood in for a machine boundary, and the ruling
closed both before the tooling step, without reopening anything else. First,
the door is not refactored out of `ownlang/ownir.py` before T_D (a separate
behavioural movement bought only for a prettier provenance line, declined),
and a hunk range by line numbers is not accepted as the boundary either (line
numbers are brittle and a hunk carries context). The boundary is structural:
`scripts/p037_door_diff_gate.py`, reading the record's `production_diff_gate`,
applied between a reference and a head. Python: `ownlang/ownir.py` stays the
treatment unit, production changes are allowed only inside the top-level
`load()` and, if one is really needed, inside a door-only helper registered by
name in the record; every other existing top-level definition must be
structurally identical to the reference, compared as AST with positions
ignored and docstrings included, and nothing may be removed. Rust: the crate
stays the carve-out so its validation tests can move as controls; production
changes are allowed only in `src/strict.rs` and in the models `struct
Function` and `struct OwnIr` of `src/lib.rs`, a new `lib.rs` item only when
registered by name; every other existing item of `lib.rs` is compared
token-wise with plain comments dropped and outer doc comments kept, and the
remaining production files of the crate (`Cargo.toml`, `src/protocol.rs`,
`src/pyrepr.rs`, `src/span.rs`) are byte-identical by git object id. Spec:
only the live sidecar contracts `spec/OwnIR.md` and `spec/ownir.schema.json`
may change, every other tracked file under `spec/` is byte-identical. The wide
units remain the technical units of the closure; the gate is the narrower
mechanical allowlist inside them, a diff-scope gate, not a new epoch and not a
refactor. Its verdicts are IDENTICAL, WITHIN_ALLOWLIST or VIOLATION; anything
it cannot decide (an unparseable file, a policy naming a definition the
reference lacks, a registration naming one the reference already has, a
production file the policy does not cover, an unknown measurement policy) is
REFUSED, never a pass. Against `6f9c373` every head before T_D and T_D itself
must be IDENTICAL; against T_D the D treatment head must be IDENTICAL or
WITHIN_ALLOWLIST, and the cumulative driver refuses a D after run whose
treatment head is not. The registrations are the only fields of the gate a D
commit may extend; `tests/test_p037_a2d_epoch.py` pins every other field, runs
the gate's synthetic controls and runs the gate on this branch. Second, the
record stores full 40-character SHAs for every predecessor (S' is
`cd7e020757de32f8a74291a0b04201275e81568d`, the S evidence
`f6214004f38258ef1bb2244d38552f233bc3f214`, its landing
`fa92c053d390e646a199d5e61b6491034cdcdc59`); a short SHA is for people until
git decides it is ambiguous. Third, the fact expectation the cumulative driver
applies is the closed machine field `measurement_policy.fact_diff`
(`unchanged` for this epoch; the closed vocabulary is `FACT_DIFF_POLICIES` in
the gate script and is mirrored by the tooling), and a missing or unknown
value is REFUSED; the prose of `claims_preregistered` is for people and is
never parsed. After this the freeze is not touched again; the next substantive
boundary is tooling, then T_D.

**Tooling (step 2).** `scripts/p037_evidence.py` now measures in the a2d
epoch and in no other: its instrument roots are the record's (the extractor
first among them), the closure is the roots minus the two carve-outs
(`instrument_pathspec()` for git, `instrument_identity()` as one digest of
the closure's blobs at a commit, so a door change moves nothing in it and an
extractor change moves it), the treatment paths are the doors and `spec/`.
Every take records `epoch` and `environment_id`, both taken from the epoch
record as committed at the take's source commit and never from an operator
string, plus the blob of that record and the instrument identity; a record
without an epoch (every a2 record), of another epoch, of another environment
or with an instrument identity that does not re-derive at its source commit is
refused, so an a2 record cannot become a before side by construction, and a
HEAD whose record disagrees with the tool's closure fails `closure_problems`.
`python scripts/p037_evidence.py identity` prints what a take at a commit
records. The cumulative driver imports the production-diff gate from the
measured checkout as a seventh measurement module (proven by path, hashed
against the treatment's blob before import) and refuses a run whose gate
blob differs between T_D and the treatment or whose treatment is not
IDENTICAL or WITHIN_ALLOWLIST against T_D; it reads the record at the
treatment for the epoch, the environment id and `measurement_policy.fact_diff`
(closed vocabulary held in three equal copies: instrument, gate, driver;
`tests/test_p037_cumulative_evidence.py` holds them equal), requires the
baseline records and the four takes to carry that epoch and environment and
T_D's instrument identity, and derives its artifact names from the epoch
(`p037-a2d-after-*.json`, `p037-a2d-cumulative.json`, `p037-a2d-manifest.md`,
baseline prefix `p037-a2d-baseline-`). Under `unchanged` the fact claims are
that every fact document is identical between before and after and that both
MOS takes count zero moved facts; under `allowed_surfaces` the a2 claims
stand as they were. No door, extractor, spec or instrument line other than
this tooling moves; the gate reports IDENTICAL against `6f9c373`. The
terminal-green head of this step is the T_D candidate; the R_D manifest names
it.

#### 10.6.14a A2.2-D: a post-freeze adjudication of the treatment/tests boundary (OWNER RULING)

10.6.14 states the D treatment "only the treatment paths and tests move,
and only within the production-diff gate against T_D." That sentence was
frozen before any D commit existed, and it undersold its own "tests move"
half: extending the `tests/` validation ledger — squarely inside that
allowance — mechanically forces two committed projections under
`docs/generated/` to move with it, because their freshness is enforced by
`tests/test_checkpoint_status.py` (itself under `tests/`, run inside
`tests/run_tests.py`), not by anything the D closure named.
`docs/generated/p022-cp1-census.md` is counted from
`tests/fixtures/ownir_validation.json` by `tests/validation_census.py`;
`docs/generated/p022-coord-census.md` is counted from the fixture tree —
the same ledger among it — by `tests/coordinate_census.py`. Neither file
is hand-typed, both are `scripts/render_checkpoint_status.py`'s own
output, and reverting them to their pre-treatment bytes while the ledger
they count has already moved would not restore the frozen boundary — it
would only turn the existing freshness gate red, which is what that gate
is for. `production_diff_gate` is no help here either: by its own
docstring it is scoped to the wide treatment units (`ownlang/ownir.py`,
`rust/crates/own-ir/`, `spec/`) and says nothing about the rest of the
tree, so its WITHIN_ALLOWLIST verdict on the D treatment commit
(`f4ca7368b0eee3ca3d8fdf03931430a97d8d8fd9`, CI run 35823596510 / `#2226`,
green) never asserted the wider sentence at all.

The gap surfaced only once that commit's full diff was checked against the
literal boundary text — after it was already pushed and CI-green, before
`named_later.D_treatment_head` was set. It is logged here as found after
the freeze, not as evidence the exception was preregistered: 10.6.14's own
text above is not amended, because it did not, in fact, say this. The
admission is narrow and mechanical, not a broadened discretion: exactly
`docs/generated/p022-cp1-census.md` and `docs/generated/p022-coord-census.md`
may differ from `T_D` alongside a D commit, and only when all three hold —
`scripts/render_checkpoint_status.py --check` exits clean on the commit
that moves them (neither is stale, and no other `docs/generated/` fragment
moves with them), and `tests/fixtures/ownir_validation.json` itself
differs from `T_D` on that same commit (the two projections track a
`tests/`-only source, never an independent edit). `tests/test_p037_a2d_epoch.py`
pins this against `T_D` by name —
`only-treatment-paths-tests-record-and-adjudicated-docs-move`,
`adjudicated-docs-projections-are-not-stale`,
`adjudicated-docs-projections-track-a-tests-only-source` — in the same
`T_D`-anchored branch that already holds the narrower `production_diff_gate`
allowlist to account.

Two older exceptions to the same literal sentence are not newly adjudicated
here, only accounted for. The epoch record's own edits
(`docs/evidence/p037-a2d-epoch.json`: `named_later`, the two registration
lists) are how this record is meant to be written, already governed by
this file's `R-D-manifest-named-with-T-D` and
`gate-registrations-are-empty-until-D-registers` checks; this formal note
is the second, being where an adjudication like this one is written down
in the first place — both are the "record" and "the note" this test
module's own docstring already names as a pair distinct from the measured
tree. The third is R_D itself (order step 4): it sits between `T_D` and
the D treatment on this branch, and the sentence being adjudicated
describes step 5, not step 4. Auditing the full `T_D..HEAD` diff for this
adjudication surfaced that R_D's evidence-only nature — verified by hand
when R_D was taken and accepted — had no standing, re-runnable check of
its own; `R-D-diff-is-evidence-only` closes that adjacent gap here rather
than leaving it for a fourth adjudication, identifying R_D by the commit
that added its own manifest rather than by a second hardcoded SHA.

Four checks in `tests/test_p037_a2d_epoch.py` carry this note:
`R-D-diff-is-evidence-only`,
`only-treatment-paths-tests-record-and-adjudicated-docs-move`,
`adjudicated-docs-projections-are-not-stale` and
`adjudicated-docs-projections-track-a-tests-only-source`. Only a
terminal-green head against which all four pass is eligible to be named
`named_later.D_treatment_head`; `f4ca7368b0eee3ca3d8fdf03931430a97d8d8fd9`
itself is not renamed or rewritten, and this adjudication lands as a
commit on top of it, never a rebase onto it.

#### 10.6.14b A2.2-D: admitting the D-after evidence landing (order step 6)

Unlike 10.6.14a, this is not a correction. The order in 10.6.14 always
named a sixth step — "D after: the governed cumulative measurement at the
D head against R_D on M2 by the pinned orchestrator" — and that step
necessarily lands evidence under `docs/evidence/`, a directory the
treatment/tests boundary (10.6.14a) never had reason to mention because
nothing there existed yet. This section, and the mechanism it describes,
exist in the tree BEFORE any of the six paths below do — the reverse
order from 10.6.14a, which was written after the gap it closes.

The D-after measurement ran at treatment `4ba49c14d8777dc94554e5ec4208a9607fb89908`
(population `T_D` = `44b405c2003b1d68965fe6346c2506d51ed52def`, baseline
`R_D` = `91a267991ba82648ecf4abd472e7ff24c39edab1`, environment
`P037_A2D_MEASUREMENT_M2`, orchestrator pinned to `44b405c2003b1d68965fe6346c2506d51ed52def`)
and returned `FACTS UNCHANGED · MOS UNCHANGED · VERDICTS UNCHANGED`,
`accepted=true`, `state=accepted`, `is_evidence=true`, all seven
`result.claims` true, zero on every layer and cross-engine matrix over 138
documents. That result is reviewed and owned; landing it changes nothing
about what was measured, only where the record of it lives.

`tests/test_p037_a2d_epoch.py`'s `D_AFTER_EVIDENCE_PINS` names the only six
paths order step 6 may add, each pinned to the exact sha256 that accepted
run produced — not "reproducible from the current tree" (there is nothing
to regenerate a historical measurement from) but "byte-identical to the
external evidence the owner already reviewed":

| path | sha256 |
|---|---|
| `docs/evidence/p037-a2d-after-mos-repo.json` | `4f084383f40a69891b3327499e88d145750681f558833fbb2d7ee2f9fe3f5bce` |
| `docs/evidence/p037-a2d-after-mos-corpus.json` | `e5a3d185dc85f52b5769eb3c5a44777806f27cec33836ac7ef00d924ba43b6e9` |
| `docs/evidence/p037-a2d-after-verdict-python.json` | `a4601b11cbf9398042b59be53f91751fa9ca1f6187c9628db1ae9d24f5a77ad7` |
| `docs/evidence/p037-a2d-after-verdict-rust.json` | `e6150987bcde281527452229bbd1615fc41a007d84143b93684a9556bbb8f0aa` |
| `docs/evidence/p037-a2d-cumulative.json` | `5aeaf5e149f26a5467f52896256cff2e16e3e5e5c4c9f11e2d85bd8aaa29cd0b` |
| `docs/evidence/p037-a2d-manifest.md` | `18912d32707f66b704c78eabdd02e26cdbef9e046a3240ab48c4af9b42e13e7b` |

`D-after-evidence-pins-match-exactly` reads each pinned path's committed
bytes with `git show` (never `git`'s own text-mode helper, which would
launder a byte-level hash through universal-newlines translation) and
refuses any content other than the pinned one; a path landing with
different bytes stays a boundary violation exactly as it would with no
exception at all, it is not silently waved through. Once
`named_later.D_after_evidence` is set, `D-after-evidence-named-correctly`
requires it to be the literal string `docs/evidence/p037-a2d-manifest.md`
— a path, mirroring `R_D_manifest`'s own shape, not a commit SHA the way
`D_treatment_head` is: D-after's manifest is its own self-describing
proof, the same relationship R_D has to its manifest, and unlike the
treatment there is no single code diff for a bare SHA to identify.

The landing keeps the same two-commit discipline as every step before it:
one evidence-only commit adding exactly these six files (nothing else
moves; the pins above make "exactly" mechanical, not a promise), then a
separate commit naming `named_later.D_after_evidence`. After that commit
lands and passes, A2.2-D is closed by this record's own order — Phase B
is a new epoch and is not started by landing this evidence.

### 10.7 Phase B entry gate: A2.2-D closed, Stage 3 discharged, §10.4 made executable

Everything below is created by this task, now — nothing in this section is
described as preregistered, and nothing in §§8-9 above is amended or
reopened by it. Three different kinds of claim appear together here on
purpose, and are labeled rather than left to blend:

**REPOSITORY FACT.** A2.2-D is closed: its order (freeze, tooling, T_D,
R_D, D treatment, D after) is fully landed at
`27aed2c455e56f71c5df6e6de4ea1601b5c9cc03`, CI is green on that head, and
`docs/evidence/p037-a2d-epoch.json`'s `named_later` carries all four
names (`T_D`, `R_D_manifest`, `D_treatment_head`, `D_after_evidence`).
Phase B is a new semantic epoch, not a continuation of a2/a2d's
analysis-and-measurement epochs, because it is the first one that changes
what a verdict *means* rather than what evidence is collected about
unchanged behaviour. It is not a new architecture, though: it is this
document's own "A1" (§8.1), the same target §8.1 already ruled on, now
given a machine-readable record
(`docs/evidence/p037-b-epoch.json`) and its own numbered branch point in
this note. Nothing about the guard vocabulary, the transform vocabulary,
the application rule, the three compatibility classes, or the kernel's
role as implementation seed is redecided here — §§2-9 remain the contract,
and a fourth compatibility class or a widened guard vocabulary during
Phase B is a case-5 event under §10.1, not a documentation update.

**MEASURED/AUDITED FACT.** P-022 Stage 3 is complete: checked directly
against `docs/proposals/P-022-rust-core-migration.md`'s own status line
("Since #262 Stage 3 the Rust core is the public default engine") and
independently corroborated by `corpus/p036-bakeoff/gv4-control-mutated-
guard/expected.json`'s own 2026-09-18 remeasurement entry at `63148d0`,
which separately cites the same cutover (PR #359). This discharges the
sequencing half of §8.1's OWNER RULING (2026-09-18) — the wait is over —
but §10.4's proof-boundary requirement is a *different* gate, standing on
its own, and is not discharged by Stage 3 completing. Because Python's
role is now exactly what the ruling anticipated ("legacy / reference /
rollback"), Phase B's treatment is Rust-only: `ownlang/ownir.py` is not a
treatment path, matching §8.1's own words for this branch of the
decision, not a new choice made here.

**REPOSITORY FACT, quoted rather than paraphrased.** §10.4's text is the
hard gate this section exists to make executable: "Phase B may not begin
semantic wiring until the P-037 proof-boundary audit is green. The audit
must derive the Kani harness inventory from source/Kani, check that the
fast and heavy CI sets are disjoint and their union equals the source
set, record the human claim and production subject for every harness,
and make every load-bearing assumption traceable to either a production
guarantor or an explicit `OUTSIDE_KANI_BOUNDARY` entry." `scripts/
p037_proof_boundary.py` is that audit; `docs/evidence/p037-b-ledger-
harnesses.json` and `docs/evidence/p037-b-ledger-assumptions.json` are
the machine-readable ledgers it checks against; `tests/
test_p037_proof_boundary.py` proves the audit actually refuses each of
the corruption modes §10.4's requirement implies, not only that it passes
on the current tree.

**Trusted-input boundary, restated rather than re-derived (already
frozen, §5 as cited in this file's own opening comment above): guard
eligibility (G-V4) and cell-local definite-release facts (G-S2/G-S3),
including which forward sits under which literal (G-S4), are assumed
correct; the kernel verifies from election, cells, solver, transforms,
collapse, finalize and application onward. The audit does not weaken this
into "proved by Kani," and does not promote any frontend assumption past
it either — §10.4's `OUTSIDE_KANI_BOUNDARY` disposition is precisely the
place that boundary is recorded as a production obligation, not silently
dropped.

**MEASURED/AUDITED FACT, current run.** Twenty-three `#[kani::proof]`
harnesses exist under `formal/p037-kernel/src/properties/` today; the
fifteen named in `ci.yml`'s `formal-p037` job and the eight named in
`formal-p037-gate.yml` are disjoint and their union is exactly those
twenty-three, checked by name, not by count alone. This is the audit's
own output at the time of writing, not a number frozen into prose the way
§8.1's history table freezes `9523fac`'s "22 of 22" — that entry describes
what A0 measured *then*; A0.5 added the G-T2b harness afterward, and nothing
here amends that history or need reconcile a stale count against a
live one, because the live count is never hand-typed at all.

**MEASURED/AUDITED FACT, a real gap.** Of the G-V4 discharge matrix's
three required negative-control families (P-037 proposal, discharge-
matrix note), family 1 (direct/compound/increment/capture write, own-body
election forbidden, no wrapper involved) has no corpus fixture: confirmed
against the complete `corpus/p036-bakeoff/` listing (eight fixtures, none
matching) and a repository-wide filename search. Families 2 and 3 are
covered (`gv4-control-mutated-guard` + `gv4-control-ref-alias-guard` for
family 2's row 18 a/b; `gv4-control-aliased-self-null` for family 3's row
19). This gap is recorded in `docs/evidence/p037-b-epoch.json`'s
`first_semantic_hypothesis.g_v4_discharge_matrix` and is not filled here:
building a correctly-measured negative control (with its own `current`/
`post_a1` record, the same discipline every existing G-V4 control
carries) is fixture work this entry-gate task did not receive as its
brief, and manufacturing one without that discipline would be worse than
naming the gap plainly.

No production file moves in this section or the record it describes.
Semantic wiring starts only after `scripts/p037_proof_boundary.py`
reports GREEN on a reviewed head, and only as a later, separate task.

#### 10.7a Phase B entry gate: family-1 finding corrected, proof boundary closed GREEN

§10.7's "real gap" paragraph above is not amended, because owner review
found it wrong, not merely incomplete: it stated family 1 "has no corpus
fixture," confirmed (its words) "against the complete `corpus/p036-bakeoff/`
listing... and a repository-wide filename search." The first half of that
search was real; the second was not as advertised — `corpus/p037-shapes/`
was never actually checked, and it holds the fixture.

**REPOSITORY FACT.** `corpus/p037-shapes/guard-mutated/case.cs` —
`Inner(Stream p, bool keep) { keep = !keep; if (!keep) p.Dispose(); }` — is
exactly family 1's own-body direct-write shape: no wrapper, the guard
parameter written before the branch reads it. Its `expected.json` (schema
`p037-fact-shape/1`, `"status": "anchored"`) pins `guarded_facts: null` on
`Inner` (G-V4 fails closed, absence is the signal, no eligible guard) and
the resulting false `OWN003` on **both** engines. It is checked by
`scripts/p037_fact_shapes.py check --engine both`, invoked from
`.github/workflows/ci.yml`'s "P-037 conformance controls + fact-shape
census" job on every push, in the same job and the same breath as
`scripts/p037_controls.py --engine both` (families 2 and 3). Two
fact-shape and control-expectation censuses, not one, jointly discharge
the G-V4 discharge matrix — a distinction this note's own §10.7 draft
did not track, because it looked only at the one it had already used for
families 2 and 3.

**MEASURED/AUDITED FACT.** The proposal's family 1 is named
"direct/compound/increment/capture write." Checked directly against
`ParameterIsStable` (`frontend/roslyn/OwnSharp.Extractor/Program.cs`,
G-V4's own implementation): a plain assignment and a compound assignment
are the same Roslyn node type (`AssignmentExpressionSyntax`, distinguished
only by `.Kind()`, which this function never switches on) hitting the
same `case` arm; a write reached only through a captured lambda is found
by the same arm too, because the scan (`body.DescendantNodes()`) walks
into nested lambda bodies without a boundary — matching the function's own
doc comment ("a write inside a lambda counts: the closure may run before
the read"). `guard-mutated`'s direct write exercises that exact arm, so a
separately-fixtured compound-assignment or captured-write case would
re-exercise the same code path already witnessed, not an independent one.
Increment/decrement (`Pre`/`PostIncrement`/`Decrement`) is a genuinely
separate `case` arm — but G-V1 restricts an eligible guard to a by-value
boolean parameter or the null-ness of a by-value reference parameter, and
neither `bool` nor an ordinary reference type has a `++`/`--` operator in
C#: there is no well-typed program in which an eligible guard is
incremented. Family 1 is therefore fully discharged by `guard-mutated`
alone, with nothing left independently unpinned.

**Consequence.** `docs/evidence/p037-b-epoch.json`'s
`first_semantic_hypothesis.g_v4_discharge_matrix` and
`docs/evidence/p037-b-ledger-assumptions.json`'s `mod.rs:337`/`347`
`negative_control` fields are corrected in place (not worth a second
freeze-then-adjudicate cycle for a sentence that was simply wrong) to
name `corpus/p037-shapes/guard-mutated` and this reasoning, rather than
"no fixture."

**Two further, unrelated findings from the same owner review, resolved in
the same follow-up.** First, the `release_cells_have_no_edges`
non-vacuity gap on the two `properties/refinement.rs` ledger rows for
`k11b_legacy_observational_compatibility_on_small_sccs` and
`k11_lfp_lax_simulation_against_today_post_finalization_on_small_sccs`: a new
`#[test] release_cells_have_no_edges_holds_non_vacuously_on_a_live_release`
(`formal/p037-kernel/src/properties/refinement.rs`) searches
`systems_exhaustive(2)` — the same well-formed, `n=2`, ≤1-edge-per-coordinate
domain `any_small_system()` draws from — and confirms a system exists with
a coordinate that is genuinely `Must`/`May`-seeded on one side and
correctly carries no edge, while a different coordinate in the same system
has a real edge, with `no_unknown_seed` also holding throughout. One test
serves both ledger rows, because they are one restriction
(`k11_lfp_lax_simulation_against_today_post_finalization_on_small_sccs`'s
assumption only additionally conjoins `no_unknown_seed`, itself already
witnessed) — not two gaps needing two witnesses. Second,
`ElectionSystem::well_formed()`
(`mod.rs:429`/`442`) had no negative control anywhere in this repository:
every existing use only ever constructs or accepts an already-well-formed
system. A new `#[test]
election_system_well_formed_rejects_an_edge_to_a_dead_coordinate`
(`formal/p037-kernel/src/properties/election.rs`) constructs an
`ElectionSystem` with an edge targeting a non-live coordinate, asserts
`well_formed()` rejects it, and asserts removing only that edge restores
well-formedness — isolating the edge as exactly what tripped the check.
Neither change touches `mos.rs`, `lower.rs`, the extractor, or any verdict;
both are non-production additions to the formal kernel's own test module,
which is what that module is for.

**MEASURED/AUDITED FACT, current run.** With the assumption ledger's two
`non_vacuity_status: "gap"` rows now `"witnessed"` and no change to the
harness inventory or the CI set split, `scripts/p037_proof_boundary.py`
reports zero problems:

```text
P-037 Phase B entry gate
PROOF BOUNDARY GREEN

semantic wiring for the frozen hypothesis in docs/evidence/p037-b-epoch.json
may now begin as a separate, later task
```

`19af74c` (this section's own originating commit, carrying the wrong
family-1 wording) is kept exactly as it was measured, not rewritten: it is
an honest record of a RED audit at the time it was taken, and this section
is where the correction is written down, the same discipline §10.6.14a
applied to its own gap.

**A third, unrelated finding from full re-verification, fixed the same
way.** `19af74c` itself, independent of anything above, had already left
`tests/test_p037_a2d_epoch.py`'s `only-treatment-paths-tests-record-and-
adjudicated-docs-move` check red: that test's allowlist predates Phase B
and had no entry for a second epoch's own top-level governance record or
a non-`tests/`-prefixed script. `tests/test_p037_a2d_epoch.py` now carries
`PHASE_B_GOVERNANCE_FILES` (the four Phase-B ledger/tool paths, exact
list, mirroring `DOCS_GENERATED_ADJUDICATED`'s shape) and
`PHASE_B_PREFIXES` (`formal/p037-kernel/`, a full prefix exception like
`tests/`, for the same reason: non-production, verification-only, and
Phase B is the first work to touch its source rather than only read it).
Logged here as discovered after the fact, the same as §10.6.14a's own
finding — not evidence either exception was preregistered.

### 10.8 Phase B / B1: the measurement instrument, frozen before the semantic treatment

§10.7a closed the Phase B entry gate GREEN at `5571ba4`. The task the owner
issued next, named **B1**, is a second, narrower gate before the first
semantic treatment: build and freeze the Phase-B measurement and
classification instrument — a production-diff gate, an environment
identity, a difference classifier, and a provenance/population contract —
all reviewed and terminal-green *before* any guarded-transfer semantics are
written. The owner's own framing, from the prompt opening this phase (a
chat directive, not a checked-in proposal document — recorded here the same
way this file's other OWNER RULING blocks record chat rulings, never
implied to be a repository file): this task "builds and freezes the
measurement/classification instrument for the first verdict-changing
semantic epoch, establishes a terminal-green 'T_B', takes a new governed
Phase-B baseline 'R_B', ... and names both only after their respective
evidence has become terminal-green," and "does NOT implement
guarded-transfer semantics. Do not touch production semantics in mos.rs or
lower_fn_params."

**Why a second instrument, not a repointed A2.2-D one.** `scripts/p037_evidence.py`,
`p037_mos_snapshot.py`, `p037_verdict_snapshot.py`, `p037_cumulative_evidence.py`
and `shadow_compare.py` are the A2.2-D measurement stack; all five are
hardwired to `EPOCH = "a2d"`, a closed `fact_diff` vocabulary
(`unchanged`/`allowed_surfaces`) built for a *zero-diff* instrument
qualification, and — for the two snapshot tools — a direct import of
`p037_evidence.evidence_fields`. Phase B is deliberately verdict-changing;
pointing that stack at Phase B by renaming files or branches would silently
misclassify a real semantic difference as instrument noise. Every function
in `p037_evidence.py` was read and sorted directly rather than assumed:
exactly 11 of its ~50 functions (`epoch_record`, `closure_problems`,
`evidence_fields`, `record_problems`, `provenance_problems`,
`comparison_problems`, `instrument_pathspec`, `instrument_manifest`,
`_record_closure_problems`, `_cli_identity`, plus its `a2d`-scoped module
constants) read epoch-specific vocabulary; the remaining ~40 (population
materialization, execution-profile capture, artifact sealing, environment
sanitization, git plumbing, manifest digesting) take their epoch as a
parameter or read nothing epoch-specific at all, and are safe to import
unmodified. That split is what makes Strategy A — a Phase-B sibling module
importing the pure half — narrower and safer than Strategy B (rewriting
the a2d instrument into an epoch-neutral core, which would require
re-proving the full A2.2-D chain's equivalence against a moving target).
B1 takes Strategy A.

**`scripts/p037_evidence_b.py`: the Phase-B provenance contract.** A new,
independent module, not an edit to `p037_evidence.py`. It sets
`EPOCH = "b"`, `EPOCH_RECORD_PATH = "docs/evidence/p037-b-epoch.json"`, its
own `INSTRUMENT_PATHS`/`INSTRUMENT_CARVE_OUTS` (the carve-out is exactly
`rust/crates/own-bridge/src/{mos,lower}.rs`, mirroring the treatment
boundary below), and `CORPUS_DIRS = (*ev.CORPUS_DIRS, "corpus/p037-shapes")`
— Phase B's own population additionally includes the fact-shape census
fixtures the A2.2-D population never needed. Its `epoch_record`,
`closure_problems`, `evidence_fields`, `record_problems` and
`provenance_problems` mirror `p037_evidence.py`'s functions of the same
name in shape only; every one delegates its actual mechanics to the
imported `ev.*` pure helpers, so zero bytes of the a2d instrument move or
change. Exercised directly at this section's own writing: `profile`
reproduces the host toolchain exactly (CPython 3.11.15, .NET SDK 8.0.425,
rustc/cargo 1.94.1, `x86_64-unknown-linux-gnu` — see the environment
paragraph below); `identity --commit HEAD` correctly fails closed on the
current, pre-B1-commit tree with three problems (two runtime paths —
`scripts/p037_evidence_b.py`, `scripts/p037_b_production_diff_gate.py` —
declared but not yet present at `HEAD`, and the epoch record at `HEAD`
naming no environment id yet), all expected: no B1 evidence can be taken
before B1's own tooling is committed; `population --source repo` names 82
files, `population --source corpus` names 192 (the increase over a2d's own
corpus population is exactly `corpus/p037-shapes`).

**REPOSITORY FACT, corrected by direct AST-boundary investigation, not
carried over from the original kernel-catalog research.** This record's
`treatment.candidate_scope` originally named `lower_fn_params` as the one
`lower.rs` seam. Reading `rust/crates/own-bridge/src/lower.rs` directly
shows that is incomplete: `lower_fn_params` (lines 1390-1463) computes only
a parameter's own OWN type-shape from its own function's `MethodSummary`
via `mos_lookup` — it never resolves a call site. The actual call-site
consumption decision — matching an argument against the *callee's*
summary, and choosing the may/unknown optimistic-default path — is made in
`fn unverified_transfer_calls` (931-972) and `fn kill_sites_for_unverified`
(977-1037); the OWN051 advisory itself is minted inline inside `fn
lower_full`, the function enclosing that block (confirmed at lines
~1964-1998 by direct source read). A guard-aware call-site selection
cannot land touching `lower_fn_params` alone: all four functions are the
honest seam. This is now `docs/evidence/p037-b-epoch.json`'s
`treatment.candidate_scope` verbatim, with its own `corrected_by` field
naming how the correction was found.

**Counted directly against the live source via `rust_items()` — the same
parser `scripts/p037_door_diff_gate.py` uses for A2.2-D — not against a
hand-maintained list.** `mos.rs` has 17 top-level items today; two —
`fn call_graph` and `fn sccs`, Tarjan's SCC condensation over a plain
adjacency map — read no `Transfer`/join value at all and stay frozen. The
other 15 (`enum Transfer`, `fn join`, `impl Transfer`, `enum PathAction`,
`enum ReturnSkeleton`, `struct ParamSkeleton`, `struct MethodSkeleton`,
`struct ParamSummary`, `struct MethodSummary`, `type Mos`, `type ParamKey`,
`fn solve_with_log`, `fn solve`, the file's one `use`, and its
`#![allow(...)]` inner attribute) are the guarded-kernel seam in `mos.rs`.
`lower.rs` has 73 top-level items; exactly the four named above are
mutable, and the other 69 stay frozen at item granularity, same as every
other production file in the unit.

**`scripts/p037_b_production_diff_gate.py`: the AST-based production-diff
gate.** Not `p037_door_diff_gate.py` repointed at a new record — that
module's `Policy`/`load_policy` require a python door, a rust door and a
spec unit together (own-ir's exact A2.2-D shape), and its own
non-registration fields are pinned by `tests/test_p037_a2d_epoch.py`
against `T_D`. The new module imports that gate's generic, `Policy`-driven
primitives (`rust_items`, `compare_rust`, `compare_items`, `snapshot`,
`memory_tree`, `resolve`, `Refused`, `UnitReport`,
`IDENTICAL`/`WITHIN_ALLOWLIST`/`VIOLATION`) unmodified — none of them read
a2d's module constants — and supplies its own `Policy`, built from
`p037-b-epoch.json`'s new `production_diff_gate.rust` object: unit
`rust/crates/own-bridge/`, zero mutable *files*, the 15+4 mutable *items*
above, an empty `registered_new_items` (by design: B1 defines no
treatment, so it has nothing to register yet — a treatment registers its
own new items in the same commit that defines them, exactly A2.2-D's own
discipline, not a relaxation of it), six frozen files (`Cargo.toml`,
`src/ast.rs`, `src/dump.rs`, `src/lib.rs`, `src/render.rs`,
`src/verdict.rs`), and `tests/` as the one control directory allowed to
change without violation. `check --reference 5571ba4 --head WORKTREE`
reports `IDENTICAL`, as `production_diff_gate.b1_must_measure` requires: B1
is tooling, ledgers and documentation, and moves no byte of
`rust/crates/own-bridge/`. Ten self-tests exercise both directions: an
identical head; an in-allowlist mutable-item change; an unnamed item
inside a mutable *file* (VIOLATION); a frozen-file change (VIOLATION); a
control-file change (no violation); a brand-new unregistered production
file (VIOLATION); a new, unregistered item inside an already-mutable file
(VIOLATION); the same new item registered (WITHIN_ALLOWLIST); and two
source-of-truth checks that the frozen mutable-item lists still match what
`rust_items()` reports against the live files today. All ten pass.

**`environment.id = P037_B_MEASUREMENT_M3`: requalified, not inherited.**
M2's own qualification is a2d-scoped evidence; reusing its identity for
Phase B by fiat would blur two epochs' environments into one. Instead,
M2's exact recipe (`provision.sh`, retained outside this repository at
`/root/p037-a2d-m2-recipe/provision.sh`) was re-hashed at B1 time and
confirmed byte-identical to `docs/evidence/p037-a2d-baseline-manifest.md`'s
recorded sha256
(`5fe4ece4c24b720f659a49bbc68b8438080c9e4b8ba554ee40f6eea94c66eb26`), and
`python scripts/p037_evidence.py profile`, run fresh in this session,
matches M2's own recorded `execution_profile`
(`docs/evidence/p037-a2d-baseline-mos-repo.json`) byte-for-byte: CPython
3.11.15, .NET SDK 8.0.425, rustc/cargo 1.94.1 with matching commit hashes,
`x86_64-unknown-linux-gnu`, the same workspace root (`/home/user/Own.NET`)
M2 used. That is a genuine requalification — independently re-measured,
not copied from the old manifest — recorded as `P037_B_MEASUREMENT_M3`
because it is a new epoch's own environment record, never a silent
inheritance of M2's. `docs/evidence/p037-b-epoch.json`'s
`environment.m2_rule` states the consequence plainly: M2 takes nothing for
this epoch and is not a control of M3; `T_D`, `R_D` and the D-after takes
are not retaken.

**`scripts/p037_b_classifier.py`: the difference classifier, frozen against
synthetic witnesses.** Section 12 of the B1 prompt requires the classifier
to exist and be frozen in `T_B`; section 17 of the same prompt requires
stopping before `T_B` if proving a class distinction would require the
semantic treatment first. Both hold at once here because they answer
different questions. `mos.rs` today has exactly one flat `Transfer` per
parameter and zero guard/`Split`/cells representation (confirmed directly
above, not assumed) — so no real, captured difference can exist yet for
the classifier to classify. What *can* be frozen now, and is, is the
classifier's own contract: three closed classes (`APPLICATION_REFINEMENT`,
`SUMMARY_REFINEMENT`, `LEGACY_HONESTY`) plus `UNCLASSIFIED`, decided from a
frozen structured `WITNESS` schema — `{coordinate, site, legacy_transfer,
guarded: {shape, finalized_cells, selection, selection_license,
collapsed}}` — never from a file path, fixture name or diagnostic code.
`check_witness()` refuses a malformed witness outright rather than
guessing at its shape. `classify()`'s rules, tested against twelve
synthetic witnesses built to match the proposal's own worked rows: an
`unknown`-collapsed, `may`-legacy witness is `LEGACY_HONESTY` regardless of
shape; for a `split` guard, a static call-site `selection` is
`APPLICATION_REFINEMENT`; absent a selection, a collapsed value strictly
above the legacy transfer in the INF-L1/L2 lattice (`no`, `must` <= `may`
<= `unknown`, `no`/`must` incomparable) is `SUMMARY_REFINEMENT`; a
collapsed value that regresses *past* the legacy transfer, or that carries
no order relation to it, is `UNCLASSIFIED`; and — the one case the
proposal's rows 1-19 do not settle — a witness carrying *both* a call-site
selection *and* an independent collapsed-value difference is
`UNCLASSIFIED` by the classifier's own design, not resolved by an invented
priority rule. Every closed class and the ambiguity rule has a positive and
a hostile-negative self-test; all twelve pass. The module names its own
gap permanently, as a module constant rather than a silent absence:
`GAP_REAL_WITNESS_SOURCE` records that no pre-treatment mechanism in this
repository can populate a real `WITNESS`, because the guarded
representation the witness describes does not exist in production yet.
That gap is structural and expected to close only once the first semantic
treatment lands — it is not a missing test or a deferred wiring task
inside B1's own scope.

**Errors caught by self-verification before anything shipped.** Three
implementation mistakes were caught by the same tests written to catch
them, not by later inspection. The diff-gate's first `_b_policy()` glue
double-unwrapped the record's `rust` section, refusing every call, until
its own selftest surfaced it — fixed by having the function accept the
`rust` section directly. One selftest's own design assumed a brand-new
*file* could be allowlisted the same way a new *item* inside an
already-mutable file can; that was wrong about `compare_rust`'s actual
semantics (a new file needs `rust_mutable_files`, not
`rust_registered_items`) and was rewritten into two correct cases —
`unregistered-new-item-in-mutable-file-is-violation` and
`registered-new-item-in-mutable-file-is-allowed` — once the mismatch was
traced. And the classifier's INF-L1/L2 lattice was initially encoded
backwards (`may <= no`/`may <= must` instead of the reverse), caught when
`summary-refinement-positive` failed with an explicit `"collapsed (must)
is not <= legacy (may)"` reason rather than a silent wrong answer. All
three are fixed in the versions described above; none reached a commit in
the broken state.

**Consequence for `named_later`.** None of `T_B`, `R_B`,
`B_treatment_head` or `B_after_evidence` is filled by this section or by
B1's own tooling commit. `T_B` is named only once this tooling is reviewed
and a head carrying it is terminal-green, including fast Kani actually
executing in CI — the same standard §10.7a's own head was held to, not a
lighter one for measurement tooling. `R_B` is then a new, governed baseline
taken *at* `T_B`, on the `P037_B_MEASUREMENT_M3` environment identity
above, over Phase B's own frozen population (repo tree plus
`corpus/p037-shapes`) — never `a2d`'s `R_D` reused or reinterpreted for a
different epoch. This record's own `order` array is otherwise unchanged by
B1, beyond the one correction already folded into `treatment.candidate_scope`
above: B1 tooling and this note land first; `T_B` and `R_B` remain "not
this task" until their own evidence is terminal-green; the first semantic
treatment remains named, scoped to `production_diff_gate.rust`'s mutable
items, and unattempted.

#### 10.8a Phase B / B1: completing the instrument's last gap before R_B

§10.8's own text on `scripts/p037_evidence_b.py` already named an open
mechanical question rather than papering over it: `p037_mos_snapshot.py`
and `p037_verdict_snapshot.py`'s `take()`/`compare()`/`verify()` bodies
call a module-global `ev` bound, at the top of each file, by a single
hardcoded `import p037_evidence as ev` — meaning both tools would stamp
epoch `"a2d"` no matter what a caller wanted, and taking R_B with them
as written was not actually possible. `4e75abe` froze the classifier,
the gate and the environment identity with that gap still open; this
addendum closes it, on top of `4e75abe`, before R_B is taken.

**REPOSITORY FACT.** Not every `ev.*` name these two tools use is
epoch-specific. `p037_evidence_b.py`'s own docstring already listed the
population/profile/artifact/environment/git/manifest mechanics it
imports unchanged from `p037_evidence.py`, stating the intent plainly:
"so `p037_mos_snapshot.py`/`p037_verdict_snapshot.py`'s existing `take()`
bodies can build a record from either module by calling the same-named
function." That sentence was aspirational until now — `p037_evidence_b`
did not yet expose those pure names at its own top level (only reachable
as `p037_evidence_b.ev.scratch_problems`, not `p037_evidence_b.
scratch_problems`), so binding a caller's `ev` to it would have raised
`AttributeError` on the first pure call. Fixed by sixteen one-line
re-exports (`scratch_problems = ev.scratch_problems`, and so on for
`execution_profile`, `build_rust_artifact`, `artifact_problems`,
`acquire_population`, `release_population`, `materialization_root`,
`new_take_dir`, `seal_artifact`, `materialize_population`,
`external_ancestor_problems`, `analysis_paths`, `sanitized_env`,
`clean_reference_profile`, `finalize_run`, `reference_contamination`) —
each one the literal same function object as `p037_evidence`'s, checked
directly (`p037_evidence_b.scratch_problems is p037_evidence.
scratch_problems` → `True`), not merely asserted.

**Design: explicit `--epoch`, no silent selection.** Both snapshot tools
gain a required `--epoch {a2d,b}` argument on every subcommand that
touches `ev` (`take`, `compare`, `verify`) — matching
`p037_verdict_snapshot.py`'s own pre-existing "ENGINE is explicit and
required" precedent for exactly the same reason, and satisfying the B1
brief's explicit list of forbidden mechanisms: no implicit "current
epoch", no branch-name inference, no silently-read environment variable.
`main()` resolves `args.epoch` against a two-entry `EPOCH_MODULES` dict
(`{"a2d": p037_evidence, "b": p037_evidence_b}`) and rebinds the
module-global `ev` to the selected module *before* calling `take()`/
`compare()`/`verify()` — whose bodies are otherwise byte-for-byte
unchanged, because every `ev.NAME` reference inside them is an attribute
lookup Python resolves at call time, not at function-definition time.
The one place that was NOT already call-time-lazy was
`p037_mos_snapshot.py`'s module-level `SOURCES` dict, which captured
`ev.CORPUS_DIRS`/`ev.REPO_TREE_DIRS` as plain tuples at import time —
before any `--epoch` argument exists to read. Replaced with a `_sources
(epoch_mod)` function called inside `take()` itself, after `ev` is
rebound, so `--epoch b` actually reaches the augmented `CORPUS_DIRS`
(`p037_evidence_b`'s tuple, plus `corpus/p037-shapes`) instead of
silently reusing a2d's.

**MEASURED/AUDITED FACT.** The a2d path was proven unbroken by real
execution against already-accepted evidence, not by code review alone:
`p037_mos_snapshot.py verify --epoch a2d docs/evidence/p037-a2d-baseline-
mos-repo.json --against 44b405c2003b1d68965fe6346c2506d51ed52def` still
reports `OK: ... fresh evidence at 44b405c2003b ...; inputs=82,
support=3`, identical to its pre-change behaviour. The same command
against current `HEAD` correctly reports `FAIL[provenance]: the
treatment changed between 44b405c2003b and HEAD` — the A2.2-D door
treatment landing after `T_D`, exactly as A2.2-D's own design intends,
and unrelated to this change. `p037_evidence_b.EPOCH_MODULES` (read via
each snapshot tool's own dict of the same name) resolves `"a2d"` to
`p037_evidence` and `"b"` to `p037_evidence_b`, with `CORPUS_DIRS`
differing exactly as designed (`"corpus/p037-shapes" in ...` is `False`
for a2d, `True` for b) and `REPO_TREE_DIRS` identical on both (b never
had a different repo-tree population). `ruff check .`, the project-wide
`mypy`, `tests/test_p037_a2d_epoch.py` (14/14) and `tests/
test_p037_evidence.py` all stay green on a clean tree; the one transient
`FAIL[fresh-record-valid]` seen while this addendum's own files were
still uncommitted was `evidence was taken on a dirty tree` — the test's
own real-`git`-backed fixture correctly reporting this checkout's actual
dirty state at that moment, not a defect in the fix, and gone once
committed.

**Consequence for T_B.** `4e75abe`'s production-diff gate verdict
(`IDENTICAL` against `5571ba4`) is untouched by this addendum — none of
its three files lie under `rust/crates/own-bridge/`. But `4e75abe` could
not actually take Phase-B evidence, so it is not offered as `T_B`: the
commit landing this addendum is, once it is itself pushed and confirmed
terminal-green (including fast Kani) the same way `4e75abe` was. `4e75abe`
stays exactly as committed, an honest record of the instrument as it
stood one step before the gap was found — the same discipline §10.7a and
§10.6.14a both already apply to their own preceding heads.

#### 10.8b Phase B / B1: two owner-review findings in the frozen instrument itself

`2ed4d92` named `T_B`/`R_B` and closed B1's own report. Owner review of
that report, independently re-verified against the live `PhysShell/Own.NET`
branch rather than accepted from the report's prose, found two real defects
in the instrument B1 had just frozen — both in governance/measurement
tooling, neither in `mos.rs`/`lower.rs` (confirmed: `5571ba4..2ed4d92`
touches no byte of either file), and both caught before any semantic
treatment could have been affected by them. Per §10.1, both are repairable
within B1's own scope (case 1, tooling defects) — no owner sign-off was
needed to fix them, only to find and rule on them, which is what this
section records.

**Finding 1 (P1): the classifier violated its own frozen overlap rule
through check ORDER, not through the rule's own text.** `classify()`
checked `class_3_shape` (`collapsed=="unknown" and legacy_t=="may"` →
`LEGACY_HONESTY`) before the split-shape overlap check (`selected in
("pos","neg") and collapse_differs` → `UNCLASSIFIED`). A witness legal
under `check_witness()` and satisfying BOTH conditions at once —
`legacy_transfer="may"`, `guarded.shape="split"`, `guarded.selection="pos"`
(with a valid license), `guarded.collapsed="unknown"` — hit the
`LEGACY_HONESTY` return first and never reached the overlap check, even
though the frozen rule (this file's own §10.8, the epoch record's
`difference_policy.rules`, and `classify()`'s own docstring) states
plainly that a witness carrying both a selection and a collapse difference
is `UNCLASSIFIED`, unconditionally. The existing overlap self-test
(`both-application-and-summary-signal-is-unclassified`) used
`collapsed="must"`, never `"unknown"`, so it could not have caught this —
it tested the rule, not the intersection with a different narrow shape's
own condition.

**MEASURED/AUDITED FACT, not argued.** The bug was confirmed by execution,
not by re-reading the code more carefully: `git show 2ed4d92:scripts/
p037_b_classifier.py`'s own `classify()`, run directly against the
counterexample witness above, returns `LEGACY_HONESTY`. The fixed version
returns `UNCLASSIFIED`. Fix: the overlap check now runs first, unconditionally,
ahead of every narrow-shape class including `LEGACY_HONESTY` — a witness
satisfying a narrow shape's own condition while also carrying an
independent selection is the overlap regardless of which narrow shape it
also matches, and checking any narrow shape first would silently resolve
that overlap in that shape's favor (itself an invented priority rule, a
§10.1 case-5 event). All twelve prior self-test cases were re-traced by
hand against the reordered logic before running them (none depend on
`LEGACY_HONESTY` and the overlap check both being reachable for the same
witness, since every existing `LEGACY_HONESTY` case uses
`selection="unselected"`, for which `has_selection` is false and the new
first check never fires) and all twelve still pass; a thirteenth,
`selection-overlapping-legacy-honesty-shape-is-unclassified`, exercises
the exact counterexample and is now the mechanical guard against this
exact regression.

**Finding 2 (P1): the production-diff gate could self-authorize.**
`check()` read the allowlist (`production_diff_gate.rust`) from the epoch
record AT THE HEAD BEING CHECKED — `doc = load_record(head_sha,
record_path, repo)`, then `pol = _b_policy(gate_section["rust"])` — not
from a reference pinned independently of that head. `frozen_policy()`
already existed as the module's own hardcoded reference policy, and its
own docstring already claimed the epoch record "must equal" it, but
nothing in `check()` (or anywhere else — confirmed by `grep -rn
frozen_policy scripts/ tests/`, no call site outside this module's own
CLI print command) ever compared the two. Consequence: a single treatment
commit could widen `production_diff_gate.rust.mutable_items` in
`docs/evidence/p037-b-epoch.json` and make the newly-widened change to
`mos.rs`/`lower.rs` at the same time, and `check()` would validate the
change against the very permission that same commit had just written —
a self-authorization hole, not a hypothetical one: `docs/evidence/
p037-b-epoch.json` is not, and was never, part of `p037_evidence_b.
INSTRUMENT_PATHS`, so `provenance_problems()` would not have flagged the
policy-section edit as instrument drift either.

**Fix, mechanical, not a documentation promise.** A new `IMMUTABLE_POLICY_
FIELDS` tuple (`unit`, `mutable_files`, `mutable_items`, `frozen_files`,
`controls` — every field except `registered_new_items`, which a treatment
is explicitly meant to grow in its own commit) and `policy_drift(record_
rust)`, which compares each of those fields against `frozen_policy()`'s
own value and returns every mismatch found. `check()` now calls it
immediately after loading the record and REFUSES (exit 2) if it returns
anything, before a `Policy` is even built. Because `scripts/
p037_b_production_diff_gate.py` is itself one of `INSTRUMENT_PATHS`,
widening `frozen_policy()` to match a self-serving epoch-record edit would
change these bytes too and surface as instrument drift the next time
`provenance_problems()` runs — the fix does not have to reimplement that
detection, only refuse to trust an unpinned record in the meantime. Six
new self-tests exercise it directly: a lone addition to `mutable_items`,
a lone removal from `frozen_files`, a changed `unit`, an emptied
`controls`, a lone `registered_new_items` addition (must NOT be refused —
that field is the one meant to move alone), and `frozen_policy()` compared
against itself (must be clean). A seventh, end-to-end check ran `check()`
against a real on-disk copy of the actual epoch record with `mos.rs`'s
`mutable_items` tampered exactly as the self-authorization scenario
describes: `REFUSED: production_diff_gate.rust.mutable_items differs from
this module's own frozen_policy()...`, exit 2 — confirmed by running it,
the tampered file deleted immediately after, never committed.

**Explicitly not extended to `p037_evidence_b.py`.** Owner review also
noted, as an optional strengthening rather than a second blocker, that
`provenance_problems()` could itself be made to check this same
projection, or the immutable-policy digest could be carried into R_B.
Not done here: the `check()`-level fix above already closes the
demonstrated hole (a treatment cannot land a `mos.rs`/`lower.rs` change
outside the frozen boundary by also editing the epoch record in the same
commit, because `check()` itself now refuses before comparing trees), and
`p037_b_production_diff_gate.py`'s own bytes are already covered by the
existing `INSTRUMENT_PATHS`/`provenance_problems()` machinery once this
fix's commit lands. Widening `p037_evidence_b.py` on top would be
repairing a hole that no longer exists rather than the one that did —
the same restraint §10.1 asks for when a red build is found: fix the
defect found, not seven adjacent things a red build makes tempting.

**Consequence for `T_B`/`R_B`.** `scripts/p037_b_production_diff_gate.py`
is one of `INSTRUMENT_PATHS`; changing it changes `instrument_identity`.
`scripts/p037_b_classifier.py` is not part of `INSTRUMENT_PATHS` at all —
the classifier interprets a difference after measurement, it does not
produce or gate one — so fixing it alone would not have forced a retake,
but fixing the gate in the same commit does. `349c7bc`'s own
`instrument_identity` (`04525002af5383fcdda0c4f0d77c9b647cc2c5f6be759b4ec
733067013e8a559`, carried by all four R_B artifacts) no longer describes
the instrument once this fix commit lands. Per owner ruling, this is
measured, not assumed: a new `T_B` is named only once this fix commit is
itself terminal-green, R_B's four takes are retaken in full at that new
head, and a fresh naming commit follows — mirroring B1's own original
order exactly, not a shortcut taken because the data is expected to be
unchanged. `349c7bc`, `40cb9b4` and `2ed4d92` are kept exactly as
committed: honest records of the instrument and its first (flawed) R_B,
superseded, not rewritten.
