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
- **Differential**: the frozen fixture *is* the differential oracle — Python
  authors the goldens (`python tests/test_diag_fixtures.py --write`), Rust
  replays them with zero Python at steady state. The 62-file corpus + 7 curated
  cases exercise acquire/release/use/move/branch/loop/return combinations.

## Deliberately preserved Python behaviors (matched, not "fixed")

- **OWN020 for syntax errors** (from checkpoint 1) — still matched.
- **Two OWN003 shapes merged**: Python emits a distinct *message* for "released
  twice" vs "may already be released on some path", but both are code **OWN003**
  at the same line; the Rust port emits OWN003 for either (only `(line, code)`
  is compared at this step). Same for the "consumed" vs "released" OWN002 split.
  This is a message-text distinction, not a verdict distinction — it returns
  when message-text parity is added (step 5). No verdict is changed.

## Integration gate (unchanged, restated)

Per owner direction, checkpoint 1's provisional-approval gate stands: **final
semantic-port merge is gated on the separate post-batch OSS remeasure** run by
another agent; this checkpoint permits implementation to proceed but does not
substitute for the broad oracle audit. If that sweep surfaces an unexplained
disappearance, it is fixed **Python-first**, the golden fixture is regenerated
explicitly, and Rust is re-brought to parity — never patched in Rust alone.

## Not done here (checkpoint 3)

`check_lifetimes` (OWN014/OWN036 escape/region) and `validate_policies`
(OWN019/OWN021/OWN023/OWN024 buffer policy) — which close the 3 deferred cases —
then evidence-slice and SARIF parity (step 5), and the effects/DI fact surface
(own-bridge, step 6).
