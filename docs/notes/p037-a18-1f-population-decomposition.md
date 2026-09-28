# P-037 A18-1F: population decomposition, final re-plan (pre-registered)

> Status: **PRE-REGISTERED.** This file is committed before any executable
> change of this gate. The boundaries below do not move after this SHA.
>
> - Base: `ca1433661cf6b62f10dfc4701fc9067647f2b612`, the exact head of #376
>   (B1 evidence completion). It is **not** the over-budget #377.
> - Branch: `research/p037-a18-1f`.
>
> `F` means **final attempt**. It is the last budget re-plan for the A18
> population-decomposition hypothesis. If this gate reaches any of its three
> caps unfinished, the approach is **killed**. There will be no A18-1G.

## 0. Owner decision (OWNER RULING, 2026-09-28, recorded in meaning)

- **#377 (A18-1R)** stays unchanged as a STOP research artifact:
  `STATE: STOP — 192 / 180`, `RUN: NONE`. It is not run, its cap is not
  edited, and it is not minified down to 180.
- **#376** is accepted as case-4 evidence infrastructure. Its scope is exact:
  - Its 36-row snapshot is a **new supplemental per-row baseline** for A18.
  - It reproduces B1's aggregates and the 8 rows B1 committed individually.
  - It proves nothing historical, row by row, about the other 28 rows,
    because B1 never committed them per row.
  - The differing extractor DLL sha stays disclosed.
- **Why a re-plan is allowed once.** The #377 STOP showed the cost
  structure. About 140 lines are measurement, coverage and reporting; about
  52 are the kill harness. The decomposition itself does not grow into a new
  solver. So the premise is alive; the executable falsifiers were mispriced.
- **Why the budget is split.** A new, prospectively frozen, split budget is
  allowed. Moving the falsifiers into another file does **not** make their
  lines free: the test module has its own cap *and* counts toward the total.
  The split is architectural, not a tax shelter.

## A. Question

Unchanged from A18-1 and A18-1R. On the frozen population `571669e`, is the
already-registered two-seam model sufficient with **only** the known
normalization reasons?

```text
G <-> L_canonical           semantic_class:       EQUAL | SUMMARY_REFINEMENT | LEGACY_HONESTY | UNEXPLAINED
L_canonical <-> L_actual    normalization_reason: EQUAL | CONSUMES_PARAM_FOLD | ARGUMENT_SHAPE_LOSS | UNEXPLAINED
```

A third normalization mechanism, however understandable, is
`RESULT: FAIL — A18-1F NORMALIZATION MODEL INCOMPLETE`. It is never an
invitation to extend the enum.

## B. Rows

- The rows are exactly the **36** comparable rows of the #376 snapshot
  `docs/evidence/p037-b1/comparable-summary-rows.json`: 28 `EQUAL` and 8
  `UNEXPLAINED`. Each is a B1 summary coordinate with both `G` and
  `L_actual`.
- They are recomputed from the frozen population with the unchanged B1
  instrument, one row per coordinate whose class is not
  `NO_GUARDED_EVIDENCE`. The row key is `(document, method, index)`.
- The 68 `NO_GUARDED_EVIDENCE` rows and all application-level rows are
  outside this gate.

## C. Definitions (fixed before measuring)

For each document, the frozen facts are extracted with the unchanged B1
instrument. `L_actual`, `G` and B1's class come from `own-guarded-report` on
those facts as emitted.

### C.1 Forward sites and eligibility

- **Coordinate:** a summary row `(method, index)` of the document's report
  whose function is in the document's facts.
- **Forward site of a coordinate:** a sidecar (`guarded_facts.calls`) call in
  that function in which the coordinate's parameter (by `ordinal`) fills a
  `param` slot.
- **Eligibility** is decided from frozen facts only. A site is **eligible**
  (canonicalized) when all of these hold:
  - **E1:** the parameter fills exactly one slot of that call;
  - **E2:** exactly one legacy body op names the parameter at the call's
    `statement_line`, and no other site already canonicalized that op;
  - **E3:** the callee coordinate resolves to exactly one report summary row
    `(callee, ordinal = slot)`, which gives the callee `index`.
- A site that fails E1–E3 is **broken**.
- **Eligibility never reads `L_actual`.** The #375 rule "rewrite only if the
  callee's `L_actual` disagrees" is forbidden. It is kept only as the
  test-only `local` mode that F0 must kill.

### C.2 L_canonical and semantic_class

- **`L_canonical`:** the unchanged production MOS, run once per document over
  facts in which **every** eligible forward site of **every** coordinate is
  represented as the canonical legacy `call`. That is A18-0's positional form:
  `{"op":"call","callee":…,"sig":…,"line":statement_line,"args":["_"]*callee_index+[param]}`.
  This applies whatever the site's current op is, and a site that is already
  a `call` is rewritten to the same form.
- **`semantic_class`:** the class `own-guarded-report` assigns to the row on
  the canonical facts, which is the existing rule `G <-> L_canonical`.
- **`G` must not move:** the row's `G` on the canonical facts must equal its
  `G` on the original facts.

### C.3 Forward closure and broken propagation

- **Forward closure of a row:** its own coordinate, plus every coordinate
  reachable through the callee coordinates of eligible sites, transitively.
- **Broken closure:** the closure contains a broken site, or a coordinate
  with no entry (for example, its function is absent from the facts). A row
  whose closure is broken is normalization **`UNEXPLAINED`**, whatever its own
  site looks like, and even when `L_actual == L_canonical`. A canonical
  surface that could not be built honestly proves nothing.

### C.4 Site mechanism and local witness

The mechanism comes from the site's actual op.

| actual op  | mechanism             | local witness |
|------------|-----------------------|---------------|
| `call`     | `EQUAL`               | not needed |
| `release`  | `CONSUMES_PARAM_FOLD` | the actual representation at this honest-forward site is `release`, and this site was replaced by the canonical forward in the canonical facts |
| `use`      | `ARGUMENT_SHAPE_LOSS` | the fold witness above, plus the already-registered wrapper probe: the frozen source with only `(T)x` / `x!` removed on that line re-extracts to `release` there |
| other      | `UNKNOWN`             | none |

- A `use` site whose wrapper probe fails is `UNKNOWN`.
- The probe is evaluated wherever it can decide a reason, which means at
  every `use` site in the closure of a row with `L_actual != L_canonical`.
- In the closure of an `EQUAL` row, mechanisms are reported only as
  metadata.

### C.5 normalization_reason

The rules apply in this order:
1. **Broken closure** gives `UNEXPLAINED`.
2. **`L_actual == L_canonical`** gives `EQUAL`, even if canonicalization
   physically rewrote sites. It is counted separately:
   - `equal_identity`: every site in the closure already was a `call`, or
     there is no site;
   - `equal_after_rewrite`: at least one site in the closure had a non-`call`
     op. This is the hidden, currently value-neutral normalization debt.
3. **`L_actual != L_canonical`** gives the non-`EQUAL` reason `R` only if
   all of these hold:
   1. the closure contains exactly one non-`EQUAL` mechanism kind, and it is
      `R`;
   2. `R` is `CONSUMES_PARAM_FOLD` or `ARGUMENT_SHAPE_LOSS`;
   3. every site of `R` in the closure satisfies its local witness (C.4);
   4. there is no `UNKNOWN` and no broken site in the closure.

   Otherwise the reason is `UNEXPLAINED`. A closure with both a fold and a
   shape loss is `UNEXPLAINED`, even though the composition is intuitively
   understood. The hypothesis promises one reason per non-equal row.

## D. Necessary conditions

- **N1: coverage.** Every snapshot row is decomposed exactly once, with no
  missing, extra or duplicated `(document, method, index)`.
- **N2: no drift.** For every row, `L_actual`, `G` and the B1 class equal the
  snapshot. Any drift makes the gate **VOID**.
- **N3:** semantic `UNEXPLAINED = 0`.
- **N4:** normalization `UNEXPLAINED = 0`, and no broken closure.
- **N5:** every non-`EQUAL` reason satisfies C.5.3, including the executable
  per-site witnesses.
- **N6:** `G` moved by canonicalization `= 0`.
- **N7:** A18-0 consistency. The 8 A18-0 rows reproduce A18-0's committed
  `L_canonical` (`docs/evidence/p037-a18/eight-rows.json`), with eight-row
  drift `= 0`.

## E. Falsifiers (run first; the population runs only if all fire)

The falsifiers live in a separate, non-auto-discovered test module,
`tests/p037_a18_1f_falsifiers.py`. It is not named `test_*.py`: `run_tests.py`
auto-discovers those, and CI has no frozen-population extractor build. Its
output is committed as evidence before the population run, and the
population is run only if it exits 0.

- **F0 (first): transitive A → B → C.** The fixture is built from the frozen
  facts of `guard-forward-bare`:
  - B = `ShapeForwardBare.Outer` forwards to C = `ShapeForwardBare.Inner`.
  - A test-only caller A forwards to B with a legacy `release`, which agrees
    with `B_actual = must`. A is never population.

  Both halves must hold:
  - the **new rule passes**: `A_canonical == B_canonical != B_actual`, and
    A's reason is `CONSUMES_PARAM_FOLD`;
  - the **old #375 local-honesty rule fails**: `A_canonical == B_actual`.

  If the old rule is not killed by this fixture, F0 is built wrongly: the
  gate STOPs and does not run the population.
- **F1:** a fold row with canonicalization disabled is no longer
  `CONSUMES_PARAM_FOLD`.
- **F2: broken links give `UNEXPLAINED`.**
  - F2a: in a cast/bang row whose own sidecar-to-forward link is broken
    (the site's `statement_line` shifted off the legacy op), the reason is
    `UNEXPLAINED`, not a fold.
  - F2b, closure propagation: in the F0 fixture, only B's site is broken. A
    must be `UNEXPLAINED`, although A's own site is intact.
- **F3:** the pure rule (C.5) gives `UNEXPLAINED` in three cases:
  - `actual = unknown`, `canonical = must`, and no mechanism;
  - a closure holding both a fold and a shape loss;
  - a broken closure with `actual == canonical`.
- **F4:** a `G` / `L_canonical` pair outside the three semantic cases is
  semantic `UNEXPLAINED`. This uses the cast row with canonicalization
  disabled (`may` vs `no`) and the real Rust classifier.
- **F5 / F6:** coverage on the complete document passes. Deleting one row
  (F5), or duplicating one (F6), fails it.

## F. Hard KILL: `RESULT: FAIL — A18-1F …`

The gate fails on any of these:
- F0 does not kill the old local-honesty rule, or any falsifier misses. The
  population is then not run.
- semantic `UNEXPLAINED > 0`;
- normalization `UNEXPLAINED > 0`;
- a broken canonicalization in any closure;
- a new normalization mechanism is needed;
- a snapshot coverage problem (missing, extra or duplicate) or drift (VOID);
- `G` changes under the canonical rewrite;
- A18-0 eight-row drift;
- information beyond the frozen facts is needed, other than the registered
  wrapper probe;
- production semantics, `ConsumesParam`, the extractor, OwnIR or facts have
  to change;
- **budget:** measurement `> 145`, tests `> 60`, or total `> 200`.

Reaching any cap unfinished gives
`RESULT: KILL — A18 POPULATION-DECOMPOSITION APPROACH (BUDGET)`. No further
budget re-plan follows.

## G. PASS: `RESULT: PASS — A18 POPULATION DECOMPOSITION HOLDS`

PASS requires all of:
- `covered = 36`, `missing = 0`, `duplicates = 0`, `extra = 0`, snapshot
  drift `= 0`;
- semantic `UNEXPLAINED = 0`, normalization `UNEXPLAINED = 0`, broken
  closures `= 0`;
- A18-0 eight-row drift `= 0`, and `G` changed by canonicalization `= 0`.

For every row, the result reports `L_actual`, `L_canonical`, `G`,
`semantic_class`, `normalization_reason`, the closure mechanisms and the
witnesses. The aggregates are the semantic counts, the normalization counts,
`equal_identity`, `equal_after_rewrite` and the
`semantic_class × normalization_reason` cross-tab.

A PASS does not make B1 pass. It establishes only this: "B1's original gate
failed, and the A18 decomposition explains that failure population-wide."
A B1 reconciliation gate needs its own authorization.

## H. Budget (all three caps are binding)

```text
measurement / decomposition / report code: <= 145 lines   (scripts/p037_a18_decompose.py, delta vs ca14336)
falsifier test module:                    <= 60 lines    (tests/p037_a18_1f_falsifiers.py, new file)
-----------------------------------------------------------------------------------------------------
TOTAL executable handwritten delta:       <= 200 lines
```

- The counting rule is the same as in A18-0 and A18-1R: added or changed
  lines in `git diff ca14336`, excluding blank lines and lines whose stripped
  text starts with `#`. Docstrings count.
- Test-module lines count toward the total; they are not an exclusion.
- No minification: the code is written in the repository's ordinary style.
- This note and the evidence JSON are not code.

## I. Non-goals

This gate does not touch any of these:
- B1: #373 and its evidence, and the #376 snapshot;
- #375 and #377;
- production MOS and verdicts, and `ConsumesParam`;
- extractor facts and semantics, OwnIR, R, A14, #368, Phase C;
- the three P-037 classes, `own-guarded`, and the application level.

It adds no normalization reason.
