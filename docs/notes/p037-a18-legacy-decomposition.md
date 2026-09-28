# P-037 A18: legacy decomposition (pre-registered)

> Status: **PRE-REGISTERED.** Committed before any implementation. The owner
> authorized implementing A18-0 right after this commit, without a further
> review stop. The boundaries below do not move after this SHA.
>
> - Base: `92cedb7`, the head of #373 (B1, `RESULT: FAIL — B1 BLOCKED (KILL 5)`).
> - Branch: `research/p037-a18-legacy-decomposition`.
>
> This is a separate kill-first gate. It does **not** continue or edit B1: #373,
> its evidence `docs/evidence/p037-b1/shadow-run.json` and its eight
> `UNEXPLAINED` rows stay exactly as committed.

## 0. Owner ruling — A18 / legacy semantic boundary (OWNER RULING, 2026-09-28, recorded verbatim in meaning)

Neither remedy proposed in B1 §H.3 is accepted:
- no fourth P-037 difference class;
- no replacing `own-bridge`'s MOS with `p037_kernel::today()` as the
  production comparison.

B1 found that two distinct things had been conflated under "legacy":

```text
L_actual     the actual production legacy MOS, after extractor-side lowering
L_canonical  the canonical legacy derivation over honest call/forward facts:
             the semantic baseline the P-037 kernel models
G            the guarded semantics
```

The three P-037 semantic difference classes govern `G <-> L_canonical`. They
do not, by themselves, establish `G <-> L_actual`. The difference
`L_actual <-> L_canonical` is a separate **pre-semantic
normalization/migration seam**, not a fourth semantic class.

The ruling's consequences:

1. There is no fourth P-037 difference class.
2. The actual `own-bridge` MOS stays the production comparison and remains
   mandatory evidence.
3. B1's eight rows stay `UNEXPLAINED` in #373, and N5 is not changed
   retroactively.
4. **Correction of stale wording.** #373 (the B1 note §H.3, its result commit
   and the PR body) says "`ConsumesParam` is frozen until Stage 3". Stage 3 has
   landed. `ConsumesParam` stays untouched because neither B1 nor A18 is
   authorized to change production semantics, not because of a Stage-3
   freeze. The committed #373 files are left as they are, per the ruling. The
   correction is recorded here, and the #373 PR body is corrected in place.

## A. Question

Can the eight B1 `UNEXPLAINED` rows be decomposed into two independently
checkable seams without a fourth guarded-semantic class?

```text
G <-> L_canonical        (P-037 semantics: the three declared classes)
L_canonical <-> L_actual (pre-semantic normalization, one reason per row)
```

## B. Phase A18-0: exactly the eight committed rows

No whole-population run. The rows are exactly those listed in
`docs/evidence/p037-b1/shadow-run.json` (`unexplained`, summary level):

| document (frozen at `571669e`) | coordinate |
|---|---|
| `corpus/p036-bakeoff/guarded-consume-negation-wrapper/{before,after}.cs` | `GuardedNegation.Outer`, `s` |
| `corpus/p036-bakeoff/guarded-consume-wrapper-forward/{before,after}.cs` | `GuardedWrapper.Outer`, `s` |
| `corpus/p037-shapes/guard-forward-bare` | `ShapeForwardBare.Outer`, `s` |
| `corpus/p037-shapes/guard-forward-negated` | `ShapeForwardNegated.Outer`, `s` |
| `corpus/p037-shapes/arg-cast-and-bang` | `ShapeCastBang.Cast`, `.Bang`, `p` |

### B.1 The three values, defined before measuring

For each row, the document is re-extracted from `571669e` with the B1
instrument; B1 proved that instrument byte-identical on this population.

- **`L_actual`**: the legacy column of `own-guarded-report` on the facts as
  emitted, which is `own-bridge`'s production MOS. It must equal the `legacy`
  value committed in B1, or the gate is void.
- **`G`**: the guarded column on the same facts. It must equal B1's `guarded`
  value.
- **`L_canonical`**: the **same production MOS algorithm, unchanged**, run on
  the same facts with exactly one op rewritten: the legacy body op of the
  row's parameter at the forwarding call's `statement_line` becomes the honest
  forward that legacy already understands. That is a `call` op with the
  sidecar call's `callee`/`sig`, and the parameter at the callee's
  params-list position (legacy `call` args are positional). The callee
  position is read from the B1 report's own coordinate rows (`ordinal` →
  `index`); nothing new is inferred.

  Inputs are the frozen `functions[]` records, their `body` and their A2
  sidecar only. No summary, no guarded value and no source text enters
  `L_canonical`.

`G` is also recomputed on the rewritten document, and it must not move. The
guarded read does not depend on how legacy lowered the call; a move would mean
the rewrite leaks into the semantics.

### B.2 Normalization reasons (NOT P-037 semantic classes)

Exactly two reasons are allowed. There is no `OTHER`, no catch-all and no
post-hoc bucket. The rule is deterministic, on the frozen facts. Every row
must have exactly one involved sidecar call and exactly one legacy op on the
parameter at its `statement_line`; otherwise the row has no reason.

| reason | rule | executable witness of how `L_actual` arose |
|---|---|---|
| `CONSUMES_PARAM_FOLD` | the op is `release`, and the callee coordinate's own `L_actual` is not `must` | (1) may-as-must: a `release` stands where the callee's own MOS value is not `must`; (2) rewriting that one op to the honest forward moves the row's MOS from `L_actual` to `L_canonical` |
| `ARGUMENT_SHAPE_LOSS` | the op is `use`, the sidecar slot is `param` (A2.2 G-C unwrapped it), and the callee coordinate's own `L_actual` is not `no` | (1) the same one-op rewrite moves `L_actual` to `L_canonical`; (2) a source probe: the frozen source with the value-preserving wrapper (`(T)x`, `x!`) removed on that one statement line re-extracts to a `release` there, so legacy saw the handle only without the wrapper |

The probe in the second row uses source text **only to witness how
`L_actual` arose**. It never enters `L_canonical`.

### B.3 Pre-registered expectation (the cheap falsifier)

```text
6 rows CONSUMES_PARAM_FOLD:  L_actual = must, L_canonical = may, G = may
2 rows ARGUMENT_SHAPE_LOSS:  L_actual = no,   L_canonical = may, G = may
=> G == L_canonical == may on 8/8, and the G <-> L_canonical class is EQUAL
```

## C. Hard KILL: `RESULT: FAIL — A18 DECOMPOSITION REFUTED`

The gate stops immediately, with no attempt to rescue B1, if:

1. any of the eight has `G != L_canonical`;
2. obtaining `L_canonical` requires modifying guarded semantics;
3. it requires changing `ConsumesParam`;
4. it requires changing OwnIR/A2 facts: the rewrite is a measurement input
   derived from the frozen facts, never a producer change;
5. `L_canonical` uses information not in the frozen B1 fact surface;
6. a row cannot be assigned exactly one deterministic reason of §B.2;
7. the gate needs a new generalized framework.

Also void (not a KILL, a broken instrument): `L_actual` or `G` differs from
the value B1 committed.

## D. PASS: `RESULT: PASS — A18 8-ROW DECOMPOSITION HOLDS`

PASS only if all of these hold:
- rows checked = 8;
- `G == L_canonical` on 8;
- a deterministic reason on 8;
- unexplained decomposition = 0;
- every reason's executable witness holds.

This PASS does not make B1 pass. It only authorizes A18-1: the same
three-way decomposition on the frozen `571669e` population. Every relevant
row there must keep `actual_legacy`, `canonical_legacy` and `guarded`, and
two independent classifications:
- `semantic_class`: the P-037 classes, `G <-> L_canonical`;
- `normalization_reason`: `EQUAL` or a reason, `L_canonical <-> L_actual`.

A row that cannot be decomposed uniquely stays `UNEXPLAINED` and blocks
Phase C.

## E. Budget and non-goals

- **Hard cap before the eight-row result: 200 new or changed handwritten
  code lines.** They are counted like B1 §F: non-blank, non-comment, and
  docstrings count. No machinery may be hidden in generated code. Reaching
  200 without the answer means **STOP: the A18 gate is too expensive, or the
  boundary is wrong.**
- The implementation is one script, `scripts/p037_a18_decompose.py`. It
  reuses the B1 driver's frozen-population helpers and the B1 binaries,
  unchanged, and writes `docs/evidence/p037-a18/eight-rows.json`.
- Not touched: `ConsumesParam`, B1's eight classifications, missing-sidecar
  behavior, R, A14, #368, Phase C, the three P-037 difference classes,
  production verdicts/MOS, `own-guarded`, and the extractor.
