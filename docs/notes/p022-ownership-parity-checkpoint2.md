# P-022 step 4 (#214) — checkpoint 2: generic solver + ownership parity

> Status: **checkpoint-2 deliverable** (generic worklist solver + the ownership
> analysis, gated by the frozen diagnostics oracle). Second of #214's three
> review checkpoints. Builds on
> [checkpoint 1](p022-diag-parity-checkpoint1.md) (the frozen
> `tests/fixtures/diag_parity.json` + comparison design). Lifetime/effect/DI and
> evidence/SARIF are checkpoint 3 / later steps.

## What landed

- **`own-analysis::solver`** — a generic monotone-lattice forward worklist
  solver (the `rustc_mir_dataflow` shape the Python `_Analyzer.fixpoint` ports
  to): `Lattice` / `ControlFlowGraph` / `Analysis` traits, RPO scheduling, a
  schedule-independent fixpoint, and a convergence guard that fails loudly on a
  non-monotone join. Dependency-free.
- **`own-analysis::ownership`** — an exact port of `ownlang/analysis.py`: the
  `{OWNED,MOVED,RELEASED,ESCAPED}` bit-lattice `State` (per-RID `u8` bitset,
  loans, handle→RID aliasing, move/acquire provenance), `join` with the Python
  invariants (block-scoped loans equal at a merge; 1:1 handle→RID), the full
  `step()` transfer over every `Instr`, the two-phase `run` (silent fixpoint,
  then emitting pass + end-of-function leak checks). RID = `SymId` (`u32`), the
  deterministic replacement for Python's `id(sym)`.

## Parity result

`tests/parity.rs` replays the frozen fixture through the ported `check` surface
(own-syntax parse → own-cfg resolver `d1` → ownership `d2`, stable-sorted by
`(line, code)`; a parse error is the preserved OWN020 quirk):

- **66 covered cases asserted, all pass exactly** (full ordered `(line, code)`
  list — no field weakened);
- **3 deferred** to checkpoint 3, listed by name: two OWN014 escape cases
  (`corpus/wpf/systemevents-region-escape`, `corpus/wpf/viewmodel-escapes-to-app`)
  and one OWN019 buffer-policy case (`curated_buffer_policy`).

### The partition is sound, not a weakening

A case is **covered** iff none of its Python codes belong to a not-yet-ported
pass. Ported at checkpoint 2: the ownership analysis (`analyze`, codes
OWN001–OWN013, OWN015–OWN017, OWN025, OWN034, OWN041) and — already parity-frozen
by #203 — the `own-cfg` resolver (`d1`). **Not** ported: `check_lifetimes`
(OWN014/OWN036) and `validate_policies` (OWN019/OWN021/OWN023/OWN024), plus the
resolver-name codes those passes can *also* emit (OWN030/OWN031) and the
OwnIR-fact sidecar families (DI\*/EFF\*/OBL\*, own-bridge step 6). For a covered
case those unported passes are provably silent, so Python's full output equals
`d1 + d2` — the exact quantity Rust computes. Covered cases are therefore
asserted on the **complete** ordered `(line, code)` list; deferred cases are
skipped whole (never half-asserted).

## Mandated correctness battery

- **Lattice laws** (`ownership.rs` unit tests): idempotent / commutative /
  associative `join` and `x <= join(x, y)`, **exhaustive** over the finite
  per-RID state space (all 16 masks × triples); plus `bottom` identity, the
  growth-reporting contract, and the two different default rules (absent RID
  **reads** as OWNED, **joins** as ∅ — the Python `.get(rid, {OWNED})` vs
  `.get(k, set())` split, pinned by a test).
- **Solver laws** (`solver.rs`, checkpoint 2a): CFG shapes (straight/diamond/
  self-loop/nested-loop/unreachable/multi-pred/abnormal-exit), exhaustive
  lattice laws on the test lattice, worklist-order independence across five
  schedules, and the convergence guard firing on a diverging join.
- **Metamorphic** (`metamorphic.rs`): renaming a local preserves `(line, code)`;
  repeated analysis is identical (determinism); adding unreachable code never
  removes a finding; diagnostics survive a serde round-trip.
- **Differential (generated)**: `tests/test_diff_gen_fixtures.py` deterministically
  generates **160 seeded mini-programs** from the ownership primitives
  (acquire/release/use/move/call(borrow|consume)/branch/loop/return), computes
  the Python `(line, code)` goldens, and freezes `source + seed + diags` into
  `tests/fixtures/diag_diff_gen.json`. `own-analysis/tests/diff_gen.rs` replays
  them with **zero Python** and, on any divergence, prints the failing **seed +
  source** so it becomes a permanent regression. 160/160 covered, exact match.
  (The frozen 69-case corpus fixture is a second, curated differential.)

## Review round 2 — the four checkpoint-2 blocking fixes

- **B1 — `State` now satisfies the `Lattice` contract.** The solver seeds a merge
  from the **first predecessor with an out-fact** (clone) and joins the rest —
  matching Python's `in_state_of`, so `join` is only ever called between two real
  predecessor states, never `bottom.join(loaded)`. `State::join` also handles the
  ⊥ identity explicitly (`⊥ ∨ x = x` with active loans) and asserts **full
  loan-map equality** (owner + kind per binding), not just key equality — a
  same-binding/different-owner-or-kind merge now fails loudly. The Python `join`
  was tightened to full-map equality **first** (a no-op: 132/132 green, fixture
  byte-identical) so the invariant is identical on both sides. New tests:
  bottom-identity-with-loans, compatible-loan commutativity/associativity,
  same-key/different-value fail-loud, and a real CFG with a `borrow_mut` spanning
  a branch merge (a loan live on both merge edges).
- **B2 — the schedules are now materially distinct.** True FIFO (`VecDeque`
  front/back) and true LIFO (`Vec` stack), not block-id-keyed aliases. A
  visit-order recorder proves ≥3 distinct visitation orders across the five
  schedules while all agree on the fixpoint; plus successor-order-permutation and
  block-ID-permutation invariance, and an ownership-specific (real `State`
  lattice) schedule-independence test over a loop+branch program.
- **B3 — no production parser edge.** `own-analysis` reads the effect type through
  `own_cfg::Effect` (re-exported by `own-cfg`); `own-syntax` moved to
  dev-dependencies (parity/metamorphic/diff-gen tests). The DAG edge test now
  filters to production (`kind: null`) deps and a dedicated assertion
  (`own_analysis_has_no_production_parser_edge`) prevents the edge returning.
- **B4 — generated differential battery** (above).

The 66/66 covered parity result is unchanged after all four fixes.

## Review round 3 — explicit lattice bottom (the one remaining blocker)

Round 2's `State::is_bottom()` inferred ⊥ from *structural emptiness* (all maps
empty), which conflated the lattice bottom with a **real reachable predecessor
that happens to carry an empty state**. That let `join(Concrete(empty),
Concrete(with_loan))` short-circuit as an identity and bypass the loan
invariant — order-independently.

Fixed by making bottom an **explicit variant**, never inferred:

```rust
enum StateFact { Bottom, Reachable(State) }
```

- `StateFact` is the solver's `Lattice::Fact`; `Bottom` is the identity, only
  ever the seed for a block none of whose predecessors are evaluated yet.
- `State::join_data` (concrete ∨ concrete) enforces the full loan invariant
  **unconditionally** — no bottom special-casing lives there.
- `join`: `⊥ ∨ x = x`, `x ∨ ⊥ = x`; `Concrete(empty) ∨ Concrete(with_loan)` (and
  the symmetric direction) **fail loudly**; `Concrete(empty) ≠ Bottom`.
- `transfer(Bottom) = Bottom` (no info in → no info out; a transient that is
  overwritten once a real predecessor arrives — a reachable block's converged
  in-fact is always `Reachable`).

New tests: `bottom_join_loan_state_is_identity`,
`concrete_empty_join_loan_state_fails_loud`,
`loan_state_join_concrete_empty_fails_loud`,
`concrete_empty_is_not_lattice_bottom`. Verified unchanged after the fix:
66/66 curated parity, 160/160 generated differential, schedule/permutation
tests, and both Python fixtures byte-identical.

## Deliberately preserved Python behaviors (matched, not "fixed")

- **OWN020 for syntax errors** (from checkpoint 1) — still matched.
- **Two OWN003 shapes merged**: Python emits a distinct *message* for "released
  twice" vs "may already be released on some path", but both are code **OWN003**
  at the same line; the Rust port emits OWN003 for either (only `(line, code)`
  is compared at this step). Same for the "consumed" vs "released" OWN002 split.
  This is a message-text distinction, not a verdict distinction — it returns
  when message-text parity is added (step 5). No verdict is changed.

## Integration gate

The separate full OSS remeasure now exists as **PR #243**; it is not re-run here.
**Final #214 merge remains gated on PR #243 being independently reviewed and
accepted/merged.** If that sweep surfaces an unexplained disappearance, it is
fixed **Python-first**, the golden fixture is regenerated explicitly, and Rust is
re-brought to parity — never patched in Rust alone.

## Checkpoint 3 scope (clarified per review)

Checkpoint 3 ports **all remaining #214 analyses as independent `own-analysis`
implementations**: **lifetime** (OWN014/OWN036 escape/region, `check_lifetimes`),
**buffer policy** (OWN019/OWN021/OWN023/OWN024, `validate_policies`), **effect**
(EFF\*), and **DI** (DI\*). `own-bridge` later *wires OwnIR facts into* the
effect/DI analyses but does **not** own their algorithms — the algorithms live in
`own-analysis`. The lifetime + buffer-policy ports close the 3 deferred cases and
bring the `.own` corpus to full parity. **Evidence-text and SARIF parity remain
later migration steps (step 5) and must not be pulled into #214** to make a
checkpoint look more complete.
