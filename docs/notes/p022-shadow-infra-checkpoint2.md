# P-022 step 7a (#260/#269) — checkpoint 2: the engine protocol

> Status: **infrastructure for shadow mode**, checkpoint 2 of the row-7a
> slice. Still not shadow mode, still no parity claim, and — this checkpoint's
> own sharpest line — **still not a comparison**. An artifact now carries two
> engines' captures side by side, and nothing reads one against the other.
> Comparing them is #260's acceptance, blocked by #259 (cp5 and 4b); the
> reduction that will consume the pairing is a later checkpoint in this same
> slice. Numbers are generated:
> [`docs/generated/p022-shadow-census.md`](../generated/p022-shadow-census.md).

Checkpoint 1 gave an input a name and a reproduction a format, with one engine
filling it. Checkpoint 2 answers the next question, which is also not a
comparison: **how does each engine report its per-layer outputs, in one
format?**

## What landed

- **`own_shadow::capture`** — the port's half of the protocol. It drives
  `own-bridge`'s three layer surfaces (`lower`, `dump_summaries`,
  `check_facts`) and reports each in the shared envelope. The reference's half
  is `ownlang/repro.py::project_layers`, and the two stay independent readings
  of one frozen format rather than one being a translation of the other.
- **`projection` on the layer envelope** (format version 2) — each layer
  declares what its engine could *produce*: `{"kind": "full"}`, or
  `{"kind": "partial", "members": [...], "reason": "..."}`.
- **An engine writes only its own entry.** The reference authors
  `python-ownlang` and carries any foreign entry through untouched; the port
  authors `rust-own-bridge` under `OWN_SHADOW_WRITE=1` and touches nothing
  else. Neither half can quietly become a comparison of one implementation
  against itself, and each is produced with **zero** of the other's runtime.
- **`own-shadow` gains `own-ir`/`own-lowered`/`own-bridge`** in the allowed DAG
  edge set — a deliberate, reviewed edit. Only entry-point crates may depend on
  `own-bridge`, and the harness is one. The constraint that runs the other way
  did not move: no core crate, nor `own-bridge` itself, may depend on the
  harness.

## Why the format needs a projection

Because the port is mid-migration, and the alternatives are both dishonest.

Two of its three layers emit the whole frozen surface — the Layer 2 lowered
document and the MOS summaries dump are byte-exact against the reference's own
goldens (#259 cp2 and cp3). The third does not: `own_bridge::check_facts` is at
the **#259 checkpoint-4 projection**, carrying every `Finding` member except
`message`, `related` and `flow`, because message synthesis (BR-V4) and the
evidence slices are cp5 and are not ported.

Without a projection field a port in that state has exactly two options:

1. **emit a short document** — and a later comparison scores the three absent
   members as agreement, which is the failure the whole differential apparatus
   exists to prevent; or
2. **refuse the layer** — and throw away the eleven members it *can* produce,
   which is a worse answer than the truth.

So the envelope carries the truth, and a test holds it to it: a partial
projection must name exactly the members its records actually have. A
projection that over-claims is the one way this field can lie, and without
that test it would be prose.

This is the cp4 discipline generalized — *a replay declares what it compares,
and the golden always carries everything* — moved from a test's docstring into
the data, where a later checkpoint can act on it.

## What the artifacts now show

Both engines' captures, side by side, with every place they part company
**declared** rather than stumbled into. Four layer envelopes across the
committed set have differing statuses, and all four are boundaries the port
states in its own error text:

| case | layer | why |
|---|---|---|
| `protocol_isloaded_violation` | `verdicts` | the obligation-protocol analysis (OBL001–005) has no `own-analysis` port; the bridge refuses rather than return a list with a family missing (#259 row 4b) |
| `verdict_door_effect_deps_not_strings` | all three | the port's **typed door** refuses the document (#294 OD-1) — and the door is upstream of every layer, so all three report the door's text |

The typed-door case is a shape a first-divergence reduction must not mistake
for a layer-level disagreement, which is why it is a committed artifact and not
a footnote: the reduction checkpoint inherits a worked example of the
distinction.

## The decisions this checkpoint took, and why

- **A door refusal is three refused layers, not one envelope-level error.**
  The format's rule is that every engine reports exactly the frozen layers; an
  engine-level error would break it, and would make "the door refused this
  document" indistinguishable from "this layer is not implemented". Their
  projections stay `full`: a refusal is *complete* information about what the
  engine did, not a partial answer.
- **The projection describes the engine's output, not the surface's version.**
  The port's verdict layer still carries `surface_version: 1` — it replays the
  reference's surface; what differs is how much of it. Conflating the two would
  have invented a second version number for one surface.
- **`surface_version` is read back out of the produced document** where the
  surface stamps one, so the envelope cannot claim a version the document does
  not carry.
- **`OWN_SHADOW_WRITE` is opt-in, and the reading tests stand down under it.**
  A suite that rewrites its own expectations on every run proves nothing, and
  "implementation disagreed with the golden → regenerate → agreement" is the
  move this family exists to make impossible. The stand-down exists because
  cargo runs a target's tests in parallel: without it a regeneration pass races
  its own readers over half-written files, and a self-inflicted flaky red is
  worse than no signal.

## Mutation campaign

Definition and recorded result:
`docs/evidence/p022-shadow-cp2.json` and its `.result.json`. Separate from checkpoint 1's on purpose
— each checkpoint's evidence stays frozen at what it measured, so a later one
cannot quietly restate an earlier one's numbers. Three layers run for every
mutation (the reference harness, and the port's two suites), no fail-fast.

**Round 1 — 11 mutations, 8 caught, 1 compile error, 2 survivors.**

- **M39 found untested code.** The port reports a typed-door refusal on all
  three layers; no committed artifact had a document the typed door refuses, so
  the path had **no control at all**. Fixed by promoting
  `verdict_door_effect_deps_not_strings` to a committed artifact — which is
  also the worked example the reduction checkpoint will want.
- **M41 found a control that stopped one step short.** `verify` requires a
  *non-empty* reason on a partial projection; only the *missing* case was
  controlled, so an empty one would have passed. Both sides gained the control.
- **M37 did not compile**, and is recorded as a compile error rather than as
  "caught": a mutation that does not build proves nothing about the tests. It
  was re-written into one that does.

**Round 2 — 11 mutations, 11 caught, 0 survivors, 0 compile errors**, control
clean.

### The gate earned its keep between the rounds

Checkpoint 2 reshaped the layer envelope, and two of checkpoint 1's mutations
(M11, M15) lost their anchors. `mutate_campaign.py --check` — which runs in
`tests/run_tests.py` and executes nothing — caught it before the recorded
result could go on describing a tree that no longer exists. They were
re-anchored and checkpoint 1's campaign re-run: **30/30**, unchanged.

That is the whole argument for a campaign being data rather than prose. A
hand-written table would have kept asserting the old numbers, and nothing would
have said otherwise.

## What checkpoint 3 needs

| # | deliverable | what it adds |
|---|---|---|
| 3 | the **`AnalysisTrace` schema** (#269) + **stable-ID normalization** | so a comparison does not break on insignificant order or on internal identifiers that differ by construction between two implementations |
| 4 | **first-divergence reduction** over the *lowered* and *MOS* layers | naming the layer, the case and the minimal difference; proven against a synthetic divergence introduced into a copy of a Layer 2 golden, and silent on unchanged data |

And the wording, unchanged: what this checkpoint proved is "two engines report
their layer outputs in one format, and each declares what it could produce" —
never "shadow mode", and never "parity".
