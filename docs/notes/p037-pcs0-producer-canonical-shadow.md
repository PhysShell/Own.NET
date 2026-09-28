# P-037 PCS-0: producer-side canonical shadow feasibility (pre-registered)

> Status: **PRE-REGISTERED.** This file is committed before any executable
> change of this gate. The boundaries below do not move after this SHA.
>
> - Base: `ca1433661cf6b62f10dfc4701fc9067647f2b612`, the head of #376.
> - Branch: `research/p037-pcs-0`.
>
> This is a new premise, not a re-plan of #378. If it passes, it stops
> before any population run and returns to the owner for the next gate.
> There is no PCS-1R2.

## 0. Owner decision (OWNER RULING, 2026-09-28, recorded in meaning)

**#378 (A18-1F)** is the terminal KILL of the *post-processing*
population-decomposition approach, i.e. rewriting OwnIR in Python after the
fact and reconstructing forward closures there.
- There is no A18-1G and no further line-budget re-plan.
- The unrun 165-line draft is not merged.
- The KILL is recorded on #304.

**Standing state:**
- #373 B1: FAIL, kept.
- #374 A18-0: PASS on its 8 rows.
- #376: the supplemental 36-row baseline.
- #375 and #377: STOP artifacts.
- Phase C stays blocked until PCS-0 passes.
- missing-sidecar, R and A14 are not touched.

**The new premise.** The extractor already holds both sides of the seam in
one place:
- the legacy body decides the ownership handoff through
  `ConsumeReleaseArgs → ConsumesParam`, which turns a forwarding call into
  `release`, or into `use` when the argument is wrapped;
- `BuildGuardedFacts` already has the honest view of the call: the A2.2
  value-preserving `Unwrap`, the resolved callee, `sig`, the declared slots,
  and `statement_line`.

So the canonical representation may live naturally at the producer. Then
the ordinary production MOS derives `L_canonical` itself, and transitivity
comes from the ordinary solver, not from a Python closure.

## A. Hypothesis

The extractor can emit, **opt-in**, a second OwnIR document in which honest
forwarding sites are legacy `call` ops instead of the premature
`release`/`use` lowering.
- Its ordinary facts output stays **byte-identical**.
- The producer decides **nothing** about `must`/`may`/`no`.

```text
normal -o output                  = byte-identical (with and without the flag, and vs the pre-change extractor)
--p037-canonical-shadow FILE      = measurement-only second document
production MOS(original facts)    = L_actual
production MOS(canonical shadow)  = L_canonical
own-guarded                       = G
```

## B. Definitions (fixed before code)

### B.1 The switch

`--p037-canonical-shadow FILE`
- The extractor runs its ordinary pipeline unchanged and writes `-o`
  exactly as without the flag.
- For every `functions[]` record, it additionally lowers the same method body
  a **second** time, with the canonical-forward representation switched on.
- It writes to `FILE` a document of the same plain shape. Its `functions[]`
  records are identical to `-o`'s, name, file, sig, params and
  `guarded_facts` included, except for `body`.
- Combined with `--fix-candidates`, the flag is refused (exit 2). Only the
  plain shape is defined.
- **No OwnIR schema change:** the shadow `call` op is the existing legacy
  `call` op, already used by the D5.2 factory path and read by
  `forward_targets` in the bridge.

### B.2 The only lowering difference

When the switch is on, at exactly the place where the legacy lowering asks
`ConsumeReleaseArgs`, the shadow looks at each argument of the expression. The
expression's top node must be an invocation resolving to a first-party,
non-reduced method. An argument is a **canonical forward** when all of these
hold:
1. it is not `ref`/`out`;
2. it binds (by name, else by position) to a non-`params` parameter of the
   callee's declaration;
3. that parameter is in the callee's `functions[].params` list, by the same
   predicate the producer already uses for that list: by-value and
   `IsOwnedDisposableType` on its declared type;
4. after the **existing** A2.2 value-preserving unwrap (parentheses, `!`,
   identity/reference casts), it is a tracked identifier.

All canonical forwards of one invocation become **one** legacy `call` op:

```text
{"op":"call", "callee":"<T>.<M>", "sig":CanonicalSig, "args":[positional over the callee's params[] list, "_" filler], "line":<the line the legacy op had>}
```

- Those identifiers get **no** `release`/`use` op for this expression.
- Every other op, tracked identifier and statement form is lowered exactly
  as before.

### B.3 What the shadow must not do

- It never calls `ConsumesParam`.
- It computes no transfer value and runs no solver.
- It builds no call graph beyond Roslyn's per-site symbol resolution, which
  the producer already does.
- It does not change `ConsumesParam`, the ordinary lowering, OwnIR, or the
  MOS.
- The A2.2 unwrap is **shared, not copied**: it may be lifted out of
  `BuildGuardedFacts` into one static helper that both paths call. The
  sidecar output must stay byte-identical, which the `-o` byte-identity
  covers.

### B.4 Measurement (the 8 A18-0 rows only)

For each row committed in `docs/evidence/p037-a18/eight-rows.json`, on its
frozen-population document at `571669e` with the rebuilt extractor:
- `L_actual` and `G` are `own-guarded-report` on `-o`.
- `L_canonical`, `G_shadow` and `semantic_class` are the same report on the
  shadow.

## C. Frozen expectation

```text
6 rows (guarded-consume-*-wrapper x2 files, guard-forward-bare, guard-forward-negated):
    L_actual = must   L_canonical = may   G = may
2 rows (ShapeCastBang.Cast, ShapeCastBang.Bang):
    L_actual = no     L_canonical = may   G = may
all 8: G_shadow == G, semantic_class == EQUAL
```

These are exactly A18-0's committed values.

## D. Falsifiers and controls, in this order

The falsifiers live in `tests/p037_pcs0_falsifiers.py`. It is not
`test_*.py`: `run_tests.py` auto-discovers those, and CI does not build the
extractor there. Its probe is `docs/evidence/p037-pcs0-probes/Transitive.cs`,
following the B0-probe precedent.

- **F0 (first): natural transitive A → B → C.**
  - The probe: C `Inner(Stream s, bool keep) { if (!keep) s.Dispose(); }`,
    B `Outer(Stream s, bool keep) { Inner(s, keep); }`, and
    A `Top(Stream s) { Outer(s, true); }`.
  - Required: `A_actual = must` (the premature `release`, because
    `ConsumesParam(Outer)` is true), `B_actual = must`, `B_shadow = may`.
  - A's shadow body holds a `call` to `Outer` at the forward line and no
    `release` there.
  - `MOS(A_shadow) = may`.
  - If the shadow still gives A a `release`, the premise is dead
    immediately.
- **F1: the producer decides no values.** A borrow chain in the same probe:
  E `Pass(Stream s) { Peek(s); }` → D `Peek(Stream s) { s.ReadByte(); }`.
  - The shadow still emits a `call` to `Peek` for E.
  - The MOS keeps `E = no` in both documents.
  - The shadow represents forwards whatever the callee does, and the value
    is the MOS's.
- **F2: `-o` is inert under the flag.** On the probe, `-o` with the flag is
  byte-identical to `-o` without it.
- **Control C1:** the pre-change vs post-change byte identity, on the whole
  frozen population. Each of the 162 documents at `571669e` is extracted
  with the pre-change extractor (built from `ca14336`) and with the new one
  without the flag. `cmp` must show every facts file byte-identical. This is
  a procedural check, recorded as evidence, not budgeted code.
- **Then the 8 A18-0 rows** (§B.4), with `-o` with vs without the flag
  byte-identical on each of their documents. They run only if F0–F2 pass.

## E. Hard KILL: `RESULT: FAIL — PCS-0 PRODUCER-SHADOW APPROACH KILLED`

The gate is killed if the shadow requires any of these:
- an OwnIR schema change;
- a change to the ordinary body lowering (anything not gated by the switch),
  or to `ConsumesParam`;
- copying a significant part of `BuildGuardedFacts`;
- a new call graph or solver, or a transfer value computed in the producer;
- a change to normal facts (F2, C1, or the per-row byte check fails);
- any cap exceeded.

It is also killed if F0 fails, F1 fails, or A18-0 is not reproduced 8/8.

If PCS-0 is killed, the next question is freezing the P-037 implementation
as a whole, not a third place for this semantics.

## F. PASS: `RESULT: PASS — PCS-0 PRODUCER CANONICAL SHADOW FEASIBLE`

PASS requires all of these:
- F0, F1 and F2 pass;
- C1 byte-identity holds on all 162 documents;
- 8/8 rows match §C, with `-o` byte-identical under the flag;
- all caps are held.

A PASS authorizes nothing further: **stop before any population run** and
return to the owner.

## G. Budget (all four caps bind)

```text
extractor shadow implementation (C#, Program.cs diff vs ca14336): <= 100
driver (Python, scripts/p037_pcs0.py, new):                       <= 40
tests / falsifiers (tests/p037_pcs0_falsifiers.py + the C# probe):  <= 60
-----------------------------------------------------------------------------
TOTAL                                                             <= 180
```

- **Counting rule:** added or changed lines in `git diff ca14336`, excluding
  blank lines and lines whose stripped text starts with `//` (C#) or `#`
  (Python). Everything else counts: braces, docstrings, and usage-text
  lines.
- The probe's C# counts toward the tests cap.
- This note and the evidence JSON are not code.
- No minification: the code is written in the repository's ordinary style.
- Reaching a cap unfinished is a KILL, not a re-plan.

## H. Non-goals

This gate does not touch any of these:
- B1 (#373) and its evidence; the #376 snapshot; A18-0's evidence;
- #375, #377 and #378;
- production MOS and verdicts; `ConsumesParam`; the ordinary lowering;
  OwnIR;
- missing-sidecar, R, A14, #368 and Phase C;
- the three P-037 classes and `own-guarded`.

There is no population run in this gate.
