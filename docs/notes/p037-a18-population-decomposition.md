# P-037 A18-1: population decomposition (pre-registered)

> Status: **STOP: HARD CAP REACHED BEFORE THE POPULATION ANSWER (§I).**
> Pre-registered in `8046688`; the boundaries did not move. The
> implementation measures 200 added code lines against the 180 cap. Neither
> `--selftest` nor the population run has been executed. There is no result,
> and no conclusion about the population.
>
> - Base: `3745975`, the head of #374 (A18-0, `RESULT: PASS — A18 8-ROW
>   DECOMPOSITION HOLDS`, accepted by the owner).
> - Branch: `research/p037-a18-population-decomposition`.
>
> B1 stays `RESULT: FAIL — B1 BLOCKED (KILL 5)` in #373, and this gate never
> declares it green. A PASS here would mean only this: "B1's original gate
> failed, and the A18 decomposition explains that failure population-wide."
> A later, separate B1-reconciliation gate would decide whether the shadow
> acceptance contract can be restated prospectively.

## A. Question

On the frozen population `571669e`, is the already-registered two-seam model
**sufficient** with **only** the normalization reasons already known?

```text
G <-> L_canonical            semantic_class      (the existing P-037 rule)
L_canonical <-> L_actual     normalization_reason
```

`normalization_reason` is exactly one of `EQUAL`, `CONSUMES_PARAM_FOLD`,
`ARGUMENT_SHAPE_LOSS` or `UNEXPLAINED`. No new reason may appear in this gate.
A fourth mechanism, even a well-understood one, is
`RESULT: FAIL — A18-1 NORMALIZATION MODEL INCOMPLETE`. It is then studied by
its own cheap gate, never added as an enum value here.

## B. Population and rows

- **Population:** exactly B1's, frozen at `571669e`: the repo tree, the 137
  corpus documents, the 23 `p037-shapes` and the B0 probes. No A18 fixture
  enters it; fixtures are for tests only.
- **Comparable rows:** every B1 summary coordinate that has both a `G` value
  and an `L_actual` value, i.e. every row whose B1 class is not
  `NO_GUARDED_EVIDENCE`. B1's committed evidence gives the expected count:
  28 `EQUAL` + 0 `SUMMARY_REFINEMENT` + 0 `LEGACY_HONESTY` + 8 `UNEXPLAINED`
  = **36**. The breakdown is corpus 14, p037-shapes 19, B0 probes 3, repo 0.
  The gate reads these numbers from the evidence file and never hardcodes
  them.
- **Outside this decomposition:** the 68 `NO_GUARDED_EVIDENCE` rows. They
  have no `G`, so there is no semantic seam to decompose. They are not
  counted as `EQUAL` and are not normalization failures.
- **Not rebuilt:** the application report (B1 already has UNEXPLAINED = 0
  there).

### B.1 What B1 committed, and what N2 can therefore check

B1 committed per-row values only for its 8 `UNEXPLAINED` rows. For the other
28 it committed per-population class counts. N2 is therefore:
- exact per row for the 8 (their `L_actual` and `G`);
- exact per population for the rest: the re-run must reproduce every
  per-population class count, and every row B1 counted as `EQUAL` must
  again have `G == L_actual`.

This gate's evidence is the first per-row record of the 28. That is a
limit of B1's evidence, stated here rather than papered over.

## C. The three values and the two columns, defined before measuring

Per document, extracted from `571669e` with the unchanged B1 instrument:

- **`L_actual`** and **`G`**: `own-guarded-report` on the facts as emitted.
- **Forwarding sites of a row** `(F, p)`: every A2 sidecar call of `F` in
  which `p` fills a `param` slot. Comparable rows passed B1's fail-closed
  join, so each site has exactly one legacy op on `p` at its
  `statement_line`.
  - **Broken join:** a site without exactly one such op makes the row's
    normalization `UNEXPLAINED` whatever the values say.
- **Which sites are normalized.** The callee coordinate is read from B1's own
  report rows (callee, `ordinal` → `index`). A site is rewritten only when
  its legacy op locally disagrees with an honest forward:
  - `release` where the callee's `L_actual` is not `must`;
  - `use` where the callee's `L_actual` is not `no`.

  Every other site is left alone: a `call` op, a `release` into a `must`
  callee, a `use` into a `no` callee. Rows are not normalized just because
  the rewrite is available.
- **`L_canonical`**: **document-wide**. The unchanged production MOS runs
  once, on the document with every normalized site of every comparable row
  rewritten to the honest positional `call` forward (the A18-0 rewrite).
  - Document-wide is required. Otherwise a caller of a normalized wrapper
    would read its callee's `L_actual`, not its `L_canonical`.
  - Comparable rows can only forward into comparable coordinates (B1 taints
    everything else), so the rewrite set is closed.
  - A row whose forward closure contains no normalized site gets
    `L_canonical = L_actual` by identity; no rewrite touches its value.
- **Site mechanism** (only the two known ones):
  - a normalized `release` site is `CONSUMES_PARAM_FOLD`;
  - a normalized `use` site is `ARGUMENT_SHAPE_LOSS` **only if** its
    executable probe holds, else the mechanism is `UNKNOWN`. The probe is
    the A18-0 probe: the frozen source with the value-preserving wrapper
    (`(T)x`, `x!`) removed on that one line re-extracts to a `release`
    there.
- **`semantic_class`**: the class `own-guarded-report` assigns on the
  canonical document. That document's legacy column is `L_canonical`, so it
  is the existing G-T2b rule, `G <-> L_canonical`: `EQUAL`,
  `SUMMARY_REFINEMENT`, `LEGACY_HONESTY` or `UNEXPLAINED`. `G` must not
  move between the two documents.
- **`normalization_reason`**:
  - `EQUAL` if `L_canonical == L_actual`. Rows with no normalized site in
    their closure (`equal_identity`) and rows with value-neutral
    normalization (`equal_after_rewrite`) are counted separately.
  - Otherwise, the unique mechanism among the normalized sites in the row's
    **forward closure**: the row's own sites, plus those of every comparable
    coordinate reachable through its sites' callees.
  - `UNEXPLAINED` if that set is empty, holds two mechanisms, or holds
    `UNKNOWN`, or if the row has a broken join.
  - There is no composite verdict; the two columns stand independently.

## D. Necessary conditions

- **N1: coverage.** Every comparable row is present exactly once. The count
  and per-population breakdown must equal B1's evidence, the 8 committed
  rows must be among them, and there are no duplicate
  `(document, method, index)` keys.
- **N2: no drift.** Per §B.1. Any drift makes the gate **VOID**.
- **N3:** `semantic_class` is always one of the existing P-037 classes, and
  `UNEXPLAINED = 0`.
- **N4:** `normalization_reason` is always `EQUAL`, `CONSUMES_PARAM_FOLD` or
  `ARGUMENT_SHAPE_LOSS`, and `UNEXPLAINED = 0`.
- **N5: witnesses.** Every non-`EQUAL` reason has an executable witness:
  - the normalization moves the row's value (`L_canonical != L_actual`);
  - every site of that mechanism in its closure satisfies the site rule
    (for a fold, the callee is not `must`; for shape loss, the probe holds).

  A coincidence of values is not a witness.

**Consistency:** the 8 A18-0 rows must reproduce A18-0's committed values.

## E. Cheap falsifiers (`--selftest`, before the population run)

Each must fire:

1. A fold row with its rewrite disabled stops being `CONSUMES_PARAM_FOLD`.
2. A cast/bang row whose sidecar-to-forward link is broken (the site's
   `statement_line` shifted off the legacy op) becomes normalization
   `UNEXPLAINED`, not a fold.
3. A synthetic row with `actual = unknown` and `canonical = must` and no
   mechanism gets `normalization_reason = UNEXPLAINED`.
4. A `G`/`L_canonical` pair outside the three semantic cases gets
   `semantic_class = UNEXPLAINED`. This is shown with the cast row and its
   rewrite disabled (`may` vs `no`), through the real Rust classifier.
5. Deleting one comparable row fails the coverage check.
6. Duplicating one comparable row fails the coverage check.

## F. Hard KILL: `RESULT: FAIL — A18-1 …`

The gate fails if any of these holds:
- semantic `UNEXPLAINED > 0`;
- normalization `UNEXPLAINED > 0`;
- a comparable row is missing;
- a row is duplicated;
- B1 `L_actual`/`G` drift (VOID);
- a new normalization reason is needed;
- information from outside the frozen B1 facts is needed, beyond the
  shape-loss witness probe;
- production MOS, `ConsumesParam`, the extractor or OwnIR has to change.

**"We found a clear third normalization cause" is still a FAIL** of this
gate (`NORMALIZATION MODEL INCOMPLETE`).

## G. PASS: `RESULT: PASS — A18 POPULATION DECOMPOSITION HOLDS`

The result block reports:
- comparable, covered, missing and duplicate counts;
- the semantic counts;
- the normalization counts (with `equal_identity` / `equal_after_rewrite`);
- B1 drift;
- the `semantic_class × normalization_reason` cross-tab.

A PASS authorizes nothing further by itself. B1 stays FAIL, and the
B1-reconciliation gate needs its own authorization.

## H. Budget and non-goals

- **Hard cap: 180 new or changed handwritten code lines relative to `#374`**,
  counted like A18-0. The work extends `scripts/p037_a18_decompose.py`
  (a `--population` and a `--selftest` mode), with no second driver.
  Reaching the cap unfinished is a **STOP: the decomposition abstraction is
  wrong.**
- Not touched: the B1 result, `missing_sidecar`, R, A14, `ConsumesParam`,
  OwnIR, extractor semantics, the application classifier, Phase C, #368, the
  three P-037 classes, production MOS/verdicts, and `own-guarded`.

## I. STOP (MEASURED OBSERVATION): the cap is reached before any answer

§H says that reaching 180 added lines unfinished is a STOP. The
implementation `scripts/p037_a18_decompose.py` measures **200** counted
lines added or changed relative to `#374` (`3745975`), counted like A18-0
(non-blank, non-comment, docstrings included). The first draft measured
**208**.

The reduction to 200 came from genuine de-duplication only, with no
formatting or golfing:
- a shorter docstring;
- an inlined single-use helper;
- a dict lookup instead of a quadratic scan;
- a print that reuses the output dict.

`ruff` and `mypy` are clean. **Neither `--selftest` nor `--population` has
been run**, because a result obtained over the cap would violate the
pre-registration. So this STOP says nothing about the population: no row was
decomposed and no falsifier was exercised.

Where the 200 lines go, roughly:

| part | lines | pre-registered by |
|---|---|---|
| forwarding-site enumeration, local-honesty test, document-wide rewrite | ~40 | §C (`L_canonical` document-wide) |
| forward-closure attribution and the reason rule | ~30 | §C (closure), N4/N5 |
| typed coverage / drift against B1's per-population counts | ~25 | N1, N2, §B.1 |
| frozen-tree / per-document plumbing (the A18-0 main still has its own copy) | ~25 | §B |
| the six falsifiers | ~40 | §E |
| verdict, cross-tab and evidence writer | ~25 | §F, §G |
| docstring, imports, small refactors of A18-0 (`ops_at`) | ~15 | |

**Reading (INFERENCE, for the owner).** Going from eight isolated rows to the
population costs more than the cap assumed, for two reasons:
- document-wide `L_canonical` needs closure attribution, which A18-0 did not;
- B1 committed no per-row values for its 28 `EQUAL` rows, so coverage and
  drift must be reconstructed from class counts.

Neither is a new semantic mechanism, but §H reads the overrun as a signal
that the abstraction may be wrong, and that is the owner's call. The honest
options are:
- raise the cap, knowing what the lines are for;
- narrow the gate, e.g. per-row `L_canonical` (A18-0's definition), which
  drops closure attribution but can misclassify callers of normalized
  wrappers;
- first make B1 commit per-row evidence (a small B1 evidence addition),
  which would shrink the coverage/drift part.

Nothing further is done until the owner decides.
