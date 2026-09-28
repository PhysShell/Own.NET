# P-037 A18-1R: population decomposition, re-planned (pre-registered)

> Status: **PRE-REGISTERED.** Committed before any executable change of this
> gate. The owner authorized implementing it and running it right after this
> commit, but only while it stays within the cap. The boundaries below do not
> move after this SHA.
>
> - Base: `ca14336`, the head of #376 (B1 evidence completion, stacked on #374). That
>   PR adds the per-row snapshot `docs/evidence/p037-b1/comparable-summary-rows.json`.
>   Its disclosed deviation (the extractor DLL sha differs from B1's, rebuilt
>   from unchanged source, with the full B1 output otherwise identical) applies here
>   too. This gate re-extracts with the same rebuilt DLL.
> - Branch: `research/p037-a18-1r`.
>
> This is a **new** gate. #375 (A18-1) stays a STOP artifact and is never run.
> B1 stays `RESULT: FAIL — B1 BLOCKED (KILL 5)` in #373.

## 0. Owner decision (OWNER RULING, 2026-09-28, recorded verbatim in meaning)

- The 180-line cap is **not** raised, because raising a cap after seeing the
  implementation is the bookkeeping kill-first exists to prevent.
- Per-row `L_canonical` is rejected, because it breaks the transitive case.
- The re-plan is B1 evidence completion (case 4, done in the base PR), then
  this gate.
- Reviewing #375 found a defect in its definition of document-wide
  `L_canonical`. #375 §C rewrote a forwarding site only when its legacy op
  locally disagreed with the callee's `L_actual`. Counterexample: A → B → C
  with `B_actual = must` and `B_canonical = may`, where A's body already
  folds A → B into `release`. The old rule sees `release` against
  `B_actual = must`, keeps A as it is, and gets `A_canonical = must`. An
  honest forward would read `B_canonical = may`.
- **Correction:** `L_actual` must never decide whether a forward is
  canonicalized. Whether `L_actual` differed from the canonical
  representation is a separate attribution question.

## A. Question

Unchanged from A18-1. On the frozen population `571669e`, is the
already-registered two-seam model sufficient with **only** the known
normalization reasons?

```text
G <-> L_canonical           semantic_class:       EQUAL | SUMMARY_REFINEMENT | LEGACY_HONESTY | UNEXPLAINED
L_canonical <-> L_actual    normalization_reason: EQUAL | CONSUMES_PARAM_FOLD | ARGUMENT_SHAPE_LOSS | UNEXPLAINED
```

A fourth mechanism, however clear, is
`RESULT: FAIL — A18-1R NORMALIZATION MODEL INCOMPLETE`. It is then studied by
its own cheap gate, never added as an enum value.

## B. Rows

The rows are exactly those of the committed B1 snapshot
`docs/evidence/p037-b1/comparable-summary-rows.json`: every B1 summary
coordinate with both `G` and `L_actual`, taken from the frozen population
with the unchanged B1 instrument. It holds **36** rows: 28 `EQUAL` and 8
`UNEXPLAINED`, including B1's 8 committed rows, which match exactly.

- **N1 and N2 are exact per row** against that snapshot. They are no longer
  reconstructed from aggregate counts.
- The 68 `NO_GUARDED_EVIDENCE` rows are outside the decomposition. They are
  not `EQUAL` and not failures.
- The application report is not rebuilt.

## C. Definitions (fixed before measuring)

For each document, the frozen facts are re-extracted with the unchanged B1
instrument.

- **`L_actual`, `G`:** `own-guarded-report` on the facts as emitted.
- **Forward site:** an A2 sidecar call of a coordinate that has a `G` value,
  in which that coordinate's parameter fills a `param` slot.
- **Eligible (canonicalized):** a site is eligible when all three hold:
  1. the sidecar says the parameter forwards at this call;
  2. the body↔sidecar placement is unambiguous, i.e. exactly one legacy op
     on the parameter at the call's `statement_line`;
  3. the callee coordinate resolves (from B1's report rows, the callee plus
     `ordinal` → `index`).

  **Eligibility never reads `L_actual`.** A site of a `G` coordinate that is
  not eligible marks the row broken; B1's join makes this impossible, so it
  is a defensive check.
- **`L_canonical`:** the unchanged production MOS, run once over the document
  in which **every** eligible site is represented as the canonical legacy
  `call` (the A18-0 positional form), whatever its current op is.
  - A site that is already a `call` is rewritten to the same form.
  - Only `G` coordinates' sites are touched. Comparable rows forward only
    into `G` coordinates, so every forward closure is covered.
- **Local mechanism of a site** (from the actual op):
  - `call` → `EQUAL`;
  - `release` → `CONSUMES_PARAM_FOLD`;
  - `use` → `ARGUMENT_SHAPE_LOSS` **only if** the already-registered wrapper
    witness holds: the frozen source with `(T)x` / `x!` removed on that one
    line re-extracts to a `release` there;
  - otherwise, and for any other op kind → `UNKNOWN`.
- **`semantic_class`:** the class `own-guarded-report` assigns on the
  canonical document, which is the existing rule `G <-> L_canonical`. `G`
  must not move between the two documents.
- **`normalization_reason`:**
  - `EQUAL` if `L_actual == L_canonical`, even when value-neutral
    representation rewrites happened inside. Those are counted separately as
    instrumentation metadata.
  - Otherwise, the non-`EQUAL` mechanisms in the row's **forward closure**
    decide: the row's own sites plus those of every coordinate reachable
    through their callees. Exactly one known mechanism gives that mechanism.
    Zero, more than one, or any `UNKNOWN` gives `UNEXPLAINED`.
  - A broken row is `UNEXPLAINED`.

## D. Necessary conditions

- **N1: coverage.** Every snapshot row is decomposed exactly once, with no
  extra and no duplicate `(document, method, index)`.
- **N2: no drift.** For every row, `L_actual`, `G` and the B1 class equal the
  snapshot. Any drift makes the gate **VOID**.
- **N3:** `semantic_class` is always an existing P-037 class, and
  `UNEXPLAINED = 0`.
- **N4:** `normalization_reason` is always `EQUAL`, `CONSUMES_PARAM_FOLD` or
  `ARGUMENT_SHAPE_LOSS`, and `UNEXPLAINED = 0`.
- **N5: witnesses.** A non-`EQUAL` reason is witnessed:
  - canonicalization moves the row's value;
  - every site of that mechanism in its closure carries it by the site rule;
  - for shape loss, the probe holds.

**Consistency:** the 8 A18-0 rows reproduce A18-0's committed values.

## E. Falsifiers (`--selftest`, run before the population, in this order)

- **F0: transitive normalization, first.** A synthetic document is built
  from the frozen facts of `guard-forward-bare`, where B = `ShapeForwardBare.Outer`
  forwards to C = `ShapeForwardBare.Inner`. It adds a test-only caller A that
  forwards to B with a legacy `release` that agrees with `B_actual = must`.
  Two things are required:
  - under this gate's rule, `A_canonical` reads `B_canonical` through the
    canonical forward, so `A_canonical == B_canonical != B_actual`;
  - the same document under the old local-honesty rule gives
    `A_canonical == B_actual`.

  **If F0 does not fire against the old rule, STOP.** A is a test fixture
  only, never population.
- **F1:** a fold row with canonicalization disabled stops being
  `CONSUMES_PARAM_FOLD`.
- **F2:** a cast/bang row whose sidecar-to-forward link is broken (the site's
  `statement_line` shifted off the legacy op) becomes normalization
  `UNEXPLAINED`, not a fold.
- **F3:** a synthetic row with `actual = unknown`, `canonical = must` and no
  mechanism gets normalization `UNEXPLAINED`.
- **F4:** a `G`/`L_canonical` pair outside the three semantic cases gets
  semantic `UNEXPLAINED`. This uses the cast row with canonicalization
  disabled (`may` vs `no`) and the real Rust classifier.
- **F5 / F6:** deleting, or duplicating, one row fails the coverage check
  against the snapshot.

## F. Hard KILL: `RESULT: FAIL — A18-1R …`

The gate fails if any of these holds:
- semantic `UNEXPLAINED > 0`;
- normalization `UNEXPLAINED > 0`;
- a row is missing or extra;
- a row is duplicated;
- drift (VOID);
- a new normalization reason is needed;
- information outside the frozen B1 facts is needed, beyond the registered
  wrapper probe;
- production MOS, `ConsumesParam`, the extractor, OwnIR or facts have to
  change;
- F0 does not fire against the old rule (STOP).

## G. PASS: `RESULT: PASS — A18 POPULATION DECOMPOSITION HOLDS`

The result reports:
- comparable, covered, missing, extra and duplicate counts;
- the semantic counts;
- the normalization counts, with value-neutral rewrites reported
  separately;
- drift;
- the `semantic_class × normalization_reason` cross-tab.

A PASS does not make B1 pass. It establishes only this: "B1's original gate
failed, and the A18 decomposition explains that failure population-wide."
A separate B1-reconciliation gate needs its own authorization.

## H. Budget and non-goals

- **Hard cap: 180 new or changed handwritten code lines in this gate's
  diff**, relative to the evidence-completion head. That excludes the
  separately capped evidence step (15/40). Lines are counted like A18-0
  (non-blank, non-comment, docstrings included).
  - The work extends `scripts/p037_a18_decompose.py`.
  - It is implemented and run **only** if it stays within 180.
  - Reaching the cap unfinished is a **STOP**.
- Not touched: production semantics, extractor facts, OwnIR, `ConsumesParam`,
  B1 (#373 and its evidence), R, A14, #368, Phase C, the three P-037 classes,
  `own-guarded`, and #375.
