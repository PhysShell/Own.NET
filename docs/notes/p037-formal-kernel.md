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
  object creation (the constructor is the callee), delegate invocation. Each
  gets its own call fact; one semantic family per A2.2 commit.
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
`member_access_on_handle` (`Use5(r.Length)`).

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
  pinned RED stays, the 52 shapes and the probe are byte-identical;
- **A2.2-5** mutation campaign: remove the handle, add parentheses, perturb the
  binding, distinguish nested calls;
- **A2.2-S** cumulative A2 after-evidence on M1 against the existing R with
  population T: fact shape MOVED as preregistered, MOS UNCHANGED, verdict
  UNCHANGED;
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
the representation the vocabulary owes), *excluded* (one of the eleven names,
attributed to the slot it sits under; every call whose argument contains the
explained site is listed as an enclosing `nested_call_result`, so
`Use(Wrap(r))` reads inner-captured / outer-excluded), *not call-related* (a
closed table of named contexts) or RED. A derived value under an argument (a
test, an interpolation hole, an index) is RED by the letter of the sentence,
never a bin. Every `var` / `param` fact must join an occurrence of the *same
symbol* at its site and ordinal, so a fact bound by spelling is RED.

It is held to a *designed* classification, not to production: the 28 probe
rows read as their frozen class (recorded in `a2_2_4_oracle`, pinned by the
freeze test), and the generated census `corpus/p037-hostile` (138 cases: 114
pairwise over site form × value flow × binding × carrier admission, plus the
named compositions, the shadowing witnesses, the member kinds and the
vocabulary edges) reads as `expected.json` designs it, occurrence by
occurrence, carrier included. The 52 A1.1/A2 census shapes and the
repository's samples are RED-free (samples: 163 universe occurrences, 25
captured, 120 excluded, 18 not call-related, 32 var/param facts all matched
by symbol).

Findings, classified by §10.1 and pinned RED by kind and count in
`corpus/p037-relevance/oracle_findings.json` (an unexpected RED fails CI; so
does a pinned RED that silently disappears):

| id | class | what | witness |
|---|---|---|---|
| F-MEMBER | 3 | expression-bodied members, struct and record methods, property accessors are outside the legacy admission *and* the orphan carrier (the gates sit inside the class / block-body loop) | probe `Box.op_Implicit`; hostile `member-*` |
| F-SHADOW | 1 | the guarded-fact handle set was keyed by spelling (`handles.Contains(lr.Local.Name)`) and the candidate collector descends into lambdas: a same-spelled non-candidate in a sibling scope, or beside a lambda-local creation, got a false `var` fact. **Repaired in A2.2-4R1** (10.6.11) | hostile `shadow-*`, now green |
| F-PARAMS-ELEMENT | 1 | an expanded params element is classified from its bare syntax: under parentheses or `!` the handle is lost (no operation of its own); under a boxing or user-defined element conversion a false opaque-and-relevant slot is emitted | hostile `pw-*-params-*` with parens / bang / boxing / user_implicit |
| F-CONDITIONAL-RECEIVER | 1 | `r?.Ext(...)` invokes through a member binding, the receiver is read from `MemberAccessExpressionSyntax` only, and ordinal 0 is dropped | hostile `ext-conditional-access` |
| F-VOCAB | 3 | four argument shapes the frozen list has no name for: a tested operand, an interpolation hole, an indexer argument, a constructor-initializer argument; production correctly emits nothing, the sentence demands a name | hostile `vocab-*` |

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
