# P-037 fact-shape baseline transition — #380

A baseline transition of the P-037 fact-shape census (`corpus/p037-shapes`) and
the conformance controls (`corpus/p036-bakeoff`), caused by an independent
production fix. It is recorded here and in every moved record
(`baseline_transitions[]` on a shape, `remeasured[]` on a control) so the
records are moved on purpose and in view.

## Old and new baseline

| | commit | what the lowering did at a guarded first-party call |
|---|---|---|
| old | `23e3203` | `ConsumesParam` treated any immediate `Dispose`/`Close` of the parameter as a consume, so a *guarded* release was lowered as an unconditional `release` of the caller's argument (the fabricated `must`). Guarded caller records survived **because** of that fabricated release. |
| new | `f164dd3` | #380: a release, or a forward to another consumer, counts only when it is definite on every normal-return path of the callee (INF-S2). A guarded one is no longer a call-site release. |

## Intentional consequences

- **Some local-caller records disappear.** A caller whose only tracked local
  is handed to a guarded consumer no longer releases it at the call. The local
  becomes an ordinary escape, so the method has no tracked local and no owned
  parameter, and its `functions[]` record is not emitted. Its `guarded_facts`
  sidecar goes with it. Shapes: `call-expression-statement`,
  `guard-bool-const-false`, `guard-bool-const-true`, `guard-mutated`,
  `guard-opaque-expression`, `guard-ref-alias`, `named-arguments-reordered`.
- **Parameter-forward wrappers move `release` → `use`.** Shapes:
  `guard-forward-bare`, `guard-forward-negated`. Their sidecar is unchanged.
- **Two verdicts move.** `guard-mutated` and `guard-ref-alias` lose the
  `OWN003` that the fabricated release caused.
- **The guarded call sidecar is no longer guaranteed to survive** ordinary
  relevance filtering: it lives on a record that relevance filtering may drop.
- **The four conformance controls' `current` now equals their `post_a1`**:
  no fabricated release, and no `OWN003` on the three G-V4 controls. `post_a1`
  itself is unchanged; it has been in the files since the controls landed
  (`afeca38`, measured at `70189a3`).

## How the loss is kept visible

The `a2_expect` entries that promised a record with a sidecar for a vanished
caller are **not deleted**. They are copied verbatim into the shape's
`baseline_transitions[].superseded.a2_expect` and replaced by an asserted
absence, `{"function": …, "record": "absent", "since": "#380"}`.
`scripts/p037_fact_shapes.py` checks that assertion by name. A record that
comes back — for example once first-party calls reach the facts canonically —
fails the census instead of being silently re-pinned. The superseded facts and
verdicts are kept in the same place.

## Classification

**ACCEPTED BASELINE MOVEMENT CAUSED BY #380.**

- NOT a P-037 implementation: no cell selection, no guard value read, no
  `guarded_facts` consumer, no OwnIR, schema or lattice change.
- NOT a reopen of #304: reopen condition 1 is **not** met. The legacy body
  still folds first-party forwards (into `release` for definite consumers, into
  `use` for parameters, and now into an escape for guarded locals), and no
  `call` op reaches either engine.
- NOT evidence that the A2 contract is satisfied: for the seven shapes above,
  the A2 promise is explicitly not met by this baseline.

## Known limitation

**Canonical first-party call transport remains absent.** The honest call
reaches the facts only through the sidecar of a record that ordinary relevance
filtering may drop. INF-S3 would summarize a wrapper that forwards its parameter
to a guarded consumer as `may`; today it is `no`, because the forward is folded
into a `use`. Reaching `may` needs a canonical call representation, which is
outside #380.
