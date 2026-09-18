# `corpus/p037-shapes` — the FACT-SHAPE census for P-037 A1.1

A small, deliberate census of the C# shapes whose **emitted facts** the A1.1
steps must preserve or must change — not a second verdict corpus.

## Why this exists

A1.1-a1 taught the lesson the hard way. The 137-file verdict corpus reported
`UNCHANGED` for a version of a1 that turned six CI jobs red, because it contains
no method that returns its own disposable parameter and the repository's own
tree does. The corpus is labelled for **verdicts**; the A1.1 steps change the
**fact surface**.

> **verdict coverage ≠ syntax / fact-shape coverage**

Two hundred more random C# files would not have closed that gap. One fixture per
shape does. Each case here pins what the extractor emits for a shape it is known
to be sensitive to, so a step that changes a shape it did not mean to touch is
caught by name rather than by a CI job failing somewhere downstream.

## Layout

    <shape>/case.cs        the minimal program
    <shape>/expected.json  what the facts must look like, and the verdict

`expected.json` records `facts` (asserted structure of the emitted
`functions[]` record) and `verdict` (the finding codes at warning severity).
A case whose shape belongs to a step that has not landed carries
`"status": "pending_a2"` with the contract it will be held to, and asserts
today's facts meanwhile — so the diff a2 produces is visible per shape instead
of aggregated into a number.

Checked by `scripts/p037_fact_shapes.py`, which names its engine explicitly
(#262 Stage 3) and runs one extractor invocation per case.
