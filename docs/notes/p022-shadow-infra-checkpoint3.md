# P-022 step 7a (#260/#269) — checkpoint 3: the `AnalysisTrace` and stable-ID normalization

> Status: **infrastructure for shadow mode**, checkpoint 3 of the row-7a
> slice. Not shadow mode, no parity claim, and **still not a comparison**: the
> trace is the *shape* a comparison would need, and producing it is not
> performing one. Numbers are generated:
> [`docs/generated/p022-shadow-census.md`](../generated/p022-shadow-census.md).

Checkpoint 2 left two engines' captures sitting side by side in one artifact.
Two things stand between that pairing and a comparison, and only one of them
should be removed.

## The problem, precisely

**Internal identifiers.** The Layer 2 handles — `sub_0`, `cap_1`, `parg_0`,
`loc_3` — are minted from **global counters in document order** (BR-L2). They
are positions wearing the costume of names. Measured on
`handles_global_counters`, reversing the component list gives:

```text
raw handles, as written   : cap_0  sub_1  sub_2  cap_3
raw handles, permuted     : sub_0  cap_1  cap_2  sub_3
```

Four facts, unchanged; eight names, none shared. A comparison over raw
documents would report every handle as a difference, and the one real
difference — the *order* — would be buried under them.

**Order.** Which is the thing that must **not** be normalized away. Document
and lowering order is semantic (BR-D4, BR-L5); BR-V8 sorts verdicts by
`(file, line, column, code)` and leaves ties in construction order, so position
carries information there too. Sorting a layer to make a comparison pass would
delete the defect the layer exists to expose.

So the trace **normalizes the identifiers and declares the order**.

## What landed

- **`ownlang/repro.py`** gains the trace projection (still the one observer
  module this slice adds to `ownlang/`, still importing nothing into the
  production path). Its docstring freezes the schema.
- **`own_shadow::project_traces`** — the port's independent reading of that
  schema.
- **`tests/fixtures/repro/<case>.trace.json`** — both engines' traces per
  artifact. Both sides project **both** engines: projecting a capture is not
  authoring it, and doing it twice is what cross-checks the *normalization
  itself*.
- **Stable ids** are `component | file | line | event | handler`, rebuilt from
  the record the bridge attached to the handle. Every occurrence of the minted
  name anywhere in the document is rewritten; the rename is a **bijection** and
  **total**, and both are asserted rather than assumed.
- **The mint kind is not discarded** — it moves onto the handle record as
  `mint`. A routing difference (R5 minting `cap_` where R6 would mint `sub_`)
  therefore stays a comparable **value on one step**, instead of splitting into
  a pair of "only in one engine" addresses that a reduction would have to
  re-join.

Measured on the same permutation:

```text
stable ids, as written : A|A.cs|3|SystemEvents.A|HA  A|A.cs|4|bus.A|HB  …
stable ids, permuted   : A|A.cs|3|SystemEvents.A|HA  A|A.cs|4|bus.A|HB  …   (identical)
lowered step order     : still different — and that difference is real
```

Both halves are asserted, on both sides, over the whole captured corpus.

## The decisions this checkpoint took, and why

- **Addresses come from identity, `~<n>` only where identity repeats.** Two
  records sharing component, file, line, event and handler are the same fact
  seen twice, and nothing but their order distinguishes them. That suffix is
  the one place position leaks back into an address, and it is recorded rather
  than hidden — a duplicate *finding* address is exactly the tie whose order
  `verdicts` declares significant.
- **A refused layer carries its error and no steps.** An empty step list that
  compared equal to another engine's empty one would score a refusal as
  agreement.
- **Nested statement bodies stay inside their statement's value.** Flattening
  deeper needs a path grammar, and the enclosing statement is already the
  smallest unit that names a lowering site.
- **The trace carries the input hash**, so it cannot be read against a document
  it did not come from.

## The finding: two readings of one schema

The two implementations disagreed, and the disagreement was in **my own
schema**, not in either engine.

`mosdump_degraded_duplicate_key` declares two functions named `Take`. The
reference addressed the second as `functions[Take~1]`; the port addressed it as
`functions[Take]~1`. Both are faithful readings of "a duplicate address takes a
`~<n>` suffix" — and the reference was, on top of that, **inconsistent with
itself**: it suffixed inside the bracket for functions and outside for every
other addressed list.

Resolved by making the rule explicit and uniform — **inside the bracket**,
everywhere. It disambiguates *which of the repeated items*, a property of the
item rather than of the path, and it is what lets a nested prefix compose:
`functions[Take~1].body[0]` addresses the second `Take`'s first statement.

This is the argument for implementing the projection twice. A single
implementation would have shipped the inconsistency, and the first comparison
built on it would have inherited it.

A second defect surfaced the same way, from this family's own step-id control:
the reference's function disambiguator reset per function, so two `Take`s
collided on one address. Found by a test, not by reading.

## Mutation campaign

Definition and recorded result: `docs/evidence/p022-shadow-cp3.json` and its `.result.json`.
**Round 1 — 11 mutations, 10 caught, 1 survivor.**

M51 (the port stops asserting the handle rewrite is total) survived, and the
diagnosis was not the code. The assertion guards a state the corpus **cannot
reach** — every statement references a handle the array lists, because the
bridge mints both — so it needed a synthetic unit-level control, which was
added on both sides (the resting place #259 cp4 chose for BR-V1's ERROR-only
rule, for the same reason: a normative rule left permanently unprovable is the
wrong answer).

It then *still* survived — because the campaign never **ran** the layer that
catches it. Its layer list covered the three integration suites and not the
crate's own unit tests. A campaign that does not run a layer cannot see it
catch, and the mutation reads as a survivor while the control exists and works.
A `rust-unit` layer was added to **all three** campaigns and all three re-run.

**Round 2 — 11 mutations, 11 caught, 0 survivors**, control clean. Checkpoints
1 and 2 re-ran unchanged at **30/30** and **11/11**.

## What checkpoint 4 needs

The last item in the row-7a slice: **first-divergence reduction** over the
*lowered* and *MOS* layers — walking the two traces in pipeline order and
naming the layer, the case and the minimal difference, classified against the
layer's declared ordering semantics. Proven against a synthetic divergence
introduced into a copy of a Layer 2 golden, and silent on unchanged data.

Everything it needs now exists: addresses that survive a counter shift, an
order it can trust the declaration of, and refusals it cannot mistake for
agreement.

And the wording, unchanged: what this checkpoint proved is "two engines'
captures are normalized into one walkable shape, and the normalization survives
a mint-order shift" — never "shadow mode", and never "parity".
