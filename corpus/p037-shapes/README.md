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

## Baseline transitions

A record that moves because a step *meant* to move it is re-recorded
deliberately, with the move written into the record itself
(`baseline_transitions[]`, which keeps the superseded facts, verdicts and
`a2_expect` verbatim). An `a2_expect` entry of the form
`{"function": …, "record": "absent"}` asserts that a record is gone on
purpose; the checker fails by name if it comes back.

- **#380** (`23e3203` → `f164dd3`): an independent INF-S2 fix stopped lowering
  a guarded release as a call-site release. Seven caller records and their
  sidecars disappear, and two wrappers move `release` → `use`. This is not a
  P-037 implementation, not a #304 reopen, and not evidence that A2 holds.
  See [`docs/notes/p037-fact-shape-baseline-transition-380.md`](../../docs/notes/p037-fact-shape-baseline-transition-380.md).
