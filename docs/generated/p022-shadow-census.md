<!-- GENERATED FILE — do not edit by hand.
     Regenerate: python scripts/render_checkpoint_status.py --write
     Checked by: tests/test_generated_docs.py (a stale copy is a red build).
     Every figure below is read out of committed evidence; none is typed. -->

# P-022 step 7a — shadow-mode infrastructure: census

**Infrastructure for shadow mode, not shadow mode.** Nothing measured here
compares two engines' end diagnostics — or any of their layer *contents*. That
comparison is #260's acceptance and is blocked on #259 (cp5 and 4b). Nothing
here is a parity claim either.

This document is the **live view** of the slice as it stands; each checkpoint's
recorded mutation campaign stays frozen at what it measured, under
`docs/notes/p022-shadow-infra-checkpoint*-data/`. Where the slice departed from
the brief it was given — the checkpoint grouping, the `-0` domain decision, the
`sha2` dependency — the departures are decisions on the record in
[the owner-decision ledger](../notes/p022-shadow-infra-owner-decisions.md),
which also states the byte-level boundary repeated in the unmeasured set below.

## The measured set — same-input capture (checkpoint 1)

| corpus | documents |
|---|---|
| `tests/fixtures/lowered` | 27 |
| `tests/fixtures/ownir` | 22 |
| `tests/fixtures/repro` | 3 |
| `tests/fixtures/summaries` | 9 |
| `tests/fixtures/verdicts` | 19 |
| **total** | **80** |

Every one of those documents is canonicalized and hashed by the reference
(`ownlang/repro.py`) and re-hashed from the same file by the port
(`own-shadow`), which is what makes "both engines saw the same input" a
checked fact rather than an assumption — **at the level of canonical document
identity**. That is a weaker statement than #260's acceptance invariant, and
the difference is named in the unmeasured set below.

| surface | count |
|---|---|
| documents captured and digest-pinned | 80 |
| tamper controls (one changed character per document, refusal required) | 80 |
| documents both engines must REFUSE to name (`domain_refusals`) | 6 |
| reproduction artifacts committed and replayed byte-for-byte | 9 |
| structural negative controls on `verify` (each side) | 18 |
| value-level domain backstop controls | 5 |

## The engine protocol (checkpoint 2)

Each engine authors only its own `engines[]` entry, and declares per layer what
it could **produce**. Over the committed artifacts:

| engine | layers produced | layers refused | projection `full` | projection `partial` |
|---|---|---|---|---|
| `python-ownlang` | 24 | 3 | 27 | 0 |
| `rust-own-bridge` | 20 | 7 | 19 | 8 |

The port's `partial` layers are its verdict surface: `own_bridge::check_facts`
is at the #259 checkpoint-4 projection, which carries every `Finding` member
except `message`, `related` and `flow`. It says so in the artifact rather than
emitting a short document a later comparison would score as agreement, and a
test asserts the claim matches the records byte for byte.

**Layer envelopes where the two engines' status differs** — structural
accounting, not a content comparison, and every one of them a boundary the port
declares rather than a disagreement it stumbled into:

| case | layer | statuses |
|---|---|---|
| `protocol_isloaded_violation` | `verdicts` | python-ownlang: produced, rust-own-bridge: refused |
| `verdict_door_effect_deps_not_strings` | `lowered` | python-ownlang: produced, rust-own-bridge: refused |
| `verdict_door_effect_deps_not_strings` | `summaries` | python-ownlang: produced, rust-own-bridge: refused |
| `verdict_door_effect_deps_not_strings` | `verdicts` | python-ownlang: produced, rust-own-bridge: refused |

## The AnalysisTrace (checkpoint 3)

Each capture is normalized into a walkable shape: internal identifiers are
replaced by addresses derived from what they identify, and each layer's
ordering semantics are **declared** rather than normalized away.

| surface | count |
|---|---|
| trace layers projected (both engines, every artifact) | 54 |
| addressed steps | 254 |
| of those, handle addresses standing in for a mint counter | 12 |

The normalization is proven on the property it exists for, over the whole
captured corpus: permuting a document's components reshuffles the global mint
counters (BR-L2) so the raw handle names change wholesale, and the **stable
ids must not move** — while the lowered layer's step **order** must still
change, because that difference is real. Both halves are asserted; a trace that
hid the second would delete the defect the layer exists to expose.

## First-divergence reduction (checkpoint 4), and the classification

The reducer walks the pair in pipeline order over **['lowered', 'summaries']** and names the
first place they part company: the layer, the step address and the *minimal*
difference inside it. The `verdicts` layer is **refused, not skipped** —
comparing final diagnostics is #260's acceptance, blocked by #259 — and the
refusal is carried in every reduction, so "not compared" can never be read as
"compared and agreed".

Over the 9 committed reductions, 8 are
`identical`. The counters below are **computed** by the reducer, not implied by
a green build:

| class | count |
|---|---|
| Python-only (`left-only`) | **0** |
| Rust-only (`right-only`) | **0** |
| Changed | **0** |
| Ordering-only | **0** |
| Unexplained | **0** |
| *status* (a layer-level disagreement, each a declared boundary) | 2 |
| *projection* (surfaces not comparable member-for-member) | 0 |

`status` and `projection` are counted apart from the four content classes on
purpose: neither is a difference in what an engine *computed*. Every `status`
row in the table above is a boundary the port declares in its own error text —
the unported obligation-protocol analysis, and the typed door.

The same-input layer carries its own counters, and those remain gate-enforced
rather than computed: the port asserts per-document equality of the canonical
identity and byte-exact equality of every committed artifact and trace, so a
non-zero counter there is not representable as a passing build. The gates:

- `own-shadow/tests/repro.rs::a_changed_byte_in_the_embedded_document_is_refused`
- `own-shadow/tests/repro.rs::every_committed_artifact_round_trips_and_verifies`
- `own-shadow/tests/repro.rs::every_declared_unnameable_document_is_refused`
- `own-shadow/tests/repro.rs::every_shared_document_hashes_to_the_recorded_digest`
- `own-shadow/tests/repro.rs::the_canonical_form_ignores_only_insignificant_text_formatting`
- `own-shadow/tests/repro.rs::values_outside_the_canonical_domain_are_refused_at_parse`
- `own-shadow/tests/engine.rs::a_partial_projection_names_exactly_the_members_it_carries`
- `own-shadow/tests/engine.rs::both_engines_report_the_same_layers_in_the_same_order`
- `own-shadow/tests/engine.rs::this_engine_reproduces_its_committed_capture`
- `own-shadow/tests/trace.rs::a_mint_order_shift_moves_the_order_but_not_the_stable_ids`
- `own-shadow/tests/trace.rs::a_refused_layer_carries_no_steps`
- `own-shadow/tests/trace.rs::every_trace_golden_is_reproduced_byte_for_byte`
- `own-shadow/tests/trace.rs::no_counter_shaped_handle_survives_anywhere_in_a_trace`
- `own-shadow/tests/trace.rs::the_declared_order_semantics_are_the_frozen_ones`
- `own-shadow/tests/reduce.rs::every_reduction_golden_is_reproduced_byte_for_byte`
- `own-shadow/tests/reduce.rs::the_reducer_is_silent_on_unchanged_data_and_names_a_synthetic_divergence`
- `own-shadow/tests/reduce.rs::the_same_fields_in_a_different_key_order_are_a_difference`
- `own-shadow/tests/reduce.rs::the_verdict_layer_is_refused_not_silently_skipped`
- `own-shadow/tests/reduce.rs::two_engines_that_both_refused_a_layer_agree`

## The unmeasured set, named

- **#260's raw-byte same-input invariant.** #260 asks that the `OwnIR`
  document be produced or loaded exactly once, that the **raw bytes** be
  hashed, and that *those exact bytes* reach both engines. What this slice
  proves is shared **canonical document identity**: each engine parses the
  file and agrees on the canonical form's digest. Canonical-equivalent input
  is not byte-identical input — two files differing in whitespace, in object
  key order, or in duplicate-key resolution share one canonical identity,
  because ignoring exactly those differences is the canonical form's job.
  Acceptance must therefore prove the byte-level invariant separately; until
  it does, "same input" here means canonical identity and nothing stronger
  ([owner decision B-1](../notes/p022-shadow-infra-owner-decisions.md)).
- **End diagnostics compared as an acceptance surface** — #260's acceptance,
  blocked by #259 (cp5 and 4b). Not attempted, not approximated.
- **The verdict layer.** Refused by the reducer, and recorded as refused in
  every reduction. This is the same blocker as the row above, stated where a
  tool could otherwise have quietly crossed it.
- **Nested statement bodies as individual steps.** A `then`/`else`/`while` body
  is part of its enclosing statement's step, so a difference inside a branch is
  reported on that statement rather than on the branch's own address.
- **Rendered-byte parity of the three layer surfaces.** The artifact carries
  layer outputs as JSON *values*, so a rendering difference (indent,
  `ensure_ascii`) is invisible here. That contract stays with each layer's own
  fixture family (`tests/test_lowered_fixtures.py`,
  `tests/test_summaries_fixtures.py`, `tests/test_verdict_fixtures.py`).
- **The strict door.** Every layer in an artifact is projected through the
  **tolerant** door, so that the three entries describe one capture. Strict-door
  behaviour is Layer 1's own family (`own-ir`'s validation controls).
- **Engine build identity.** The artifact names *which* engine, never which
  build of it — a version stamp would make an artifact non-reproducible from
  the same inputs.
- **Nesting-depth agreement.** CPython's recursion limit and `serde_json`'s
  128-level cap differ; `spec/OwnIR.md` §4.2 bounds a conforming document
  well inside both, so no conforming document reaches the difference.

## Mutation campaigns

Definitions and recorded results live under
`docs/notes/p022-shadow-infra-checkpoint*-data/`. Every layer runs for every
mutation (P-022 discipline 3: no fail-fast), and every mutation edits a
**production** surface (discipline 2). The runs are recorded, not reproduced in
CI; what CI gates is that each definition still **anchors** to this tree and
that each recorded result is internally consistent
(`tests/test_generated_docs.py`).

### checkpoint 1 — capture and artifact (`p022-shadow-cp1`)

| | |
|---|---|
| mutations | **30** |
| caught | **30** |
| survived | **0** |
| compile errors (reported as such, never as "caught") | 0 |
| harness-honesty controls reporting zero failures | 1 |
| catches by layer | `python` 19, `rust` 40 |
| mutations with exactly **one** catching layer | 15 — M04, M05, M06, M07, M08, M09, M10, M11, M12, M14, M15, M21, M24, M25, M26 |

| id | mutation | caught by |
|---|---|---|
| M01 | the reference's canonical form stops sorting keys | `python::artifact-golden`, `python::digest-ledger` |
| M02 | the reference's canonical form escapes non-ASCII instead of emitting it raw | `python::artifact-golden`, `python::digest-ledger` |
| M03 | the reference's canonical form re-introduces insignificant whitespace | `python::artifact-golden`, `python::digest-ledger` |
| M04 | the reference stops refusing the literal -0 | `python::domain-refusal` |
| M05 | the reference stops bounding integer literals to signed 64 bits | `python::domain-refusal-reason` |
| M06 | the reference accepts a float literal instead of refusing it | `python::domain-refusal-reason` |
| M07 | the reference accepts NaN/Infinity, which serde_json rejects as invalid JSON | `python::domain-refusal-reason` |
| M08 | the reference's VALUE-level domain backstop stops refusing a float | `python::domain-backstop` |
| M09 | the reference's verification stops comparing the recomputed hash | `python::tamper-refusal` |
| M10 | the reference stops lifting a layer refusal into the envelope's status | `python::artifact-golden` |
| M11 | the reference stops lifting surface_version into the layer envelope | `python::artifact-golden` |
| M12 | the reference stops carrying the document's own declared schema version | `python::artifact-golden` |
| M13 | the reference reorders the frozen layer vocabulary | `python::artifact-verify`, `python::capture-verify` |
| M14 | the reference's verification stops checking the frozen engine order | `python::structural-control` |
| M15 | the reference renders the artifact with a different indent | `python::artifact-golden` |
| M16 | the port's canonical form stops sorting object keys | `rust::every_committed_artifact_round_trips_and_verifies`, `rust::every_shared_document_hashes_to_the_recorded_digest`, `rust::this_engine_reproduces_its_committed_capture`, `rust::verify_refuses_each_structural_violation` |
| M17 | the port escapes U+007F, which the reference emits raw | `rust::every_committed_artifact_round_trips_and_verifies`, `rust::every_shared_document_hashes_to_the_recorded_digest`, `rust::this_engine_reproduces_its_committed_capture` |
| M18 | the port escapes control code points with uppercase hex | `rust::every_committed_artifact_round_trips_and_verifies`, `rust::every_shared_document_hashes_to_the_recorded_digest`, `rust::this_engine_reproduces_its_committed_capture` |
| M19 | the port renders the artifact with a different indent width | `rust::every_committed_artifact_round_trips_and_verifies`, `rust::every_trace_golden_is_reproduced_byte_for_byte`, `rust::the_canonical_form_ignores_only_insignificant_text_formatting` |
| M20 | the port renders an artifact's objects in sorted rather than document order | `rust::every_committed_artifact_round_trips_and_verifies`, `rust::every_trace_golden_is_reproduced_byte_for_byte`, `rust::the_canonical_form_ignores_only_insignificant_text_formatting` |
| M21 | the port resolves a duplicate key first-wins instead of last-wins | `rust::the_canonical_form_ignores_only_insignificant_text_formatting` |
| M22 | the port wraps an out-of-i64 integer instead of refusing it | `rust::every_declared_unnameable_document_is_refused`, `rust::values_outside_the_canonical_domain_are_refused_at_parse` |
| M23 | the port accepts a float as an integer instead of refusing it | `rust::every_declared_unnameable_document_is_refused`, `rust::values_outside_the_canonical_domain_are_refused_at_parse` |
| M24 | the port's verification stops comparing the recomputed digest | `rust::a_changed_byte_in_the_embedded_document_is_refused` |
| M25 | the port's verification stops checking the frozen layer order | `rust::verify_refuses_each_structural_violation` |
| M26 | the port's verification stops checking the frozen engine order | `rust::verify_refuses_each_structural_violation` |
| M27 | the port renders the digest with uppercase hex | `rust::every_committed_artifact_round_trips_and_verifies`, `rust::every_shared_document_hashes_to_the_recorded_digest`, `rust::this_engine_reproduces_its_committed_capture`, `rust::verify_refuses_each_structural_violation` |
| M28 | the port hashes the RENDERING form instead of the canonical form | `rust::every_committed_artifact_round_trips_and_verifies`, `rust::every_shared_document_hashes_to_the_recorded_digest`, `rust::the_canonical_form_ignores_only_insignificant_text_formatting`, `rust::this_engine_reproduces_its_committed_capture`, `rust::verify_refuses_each_structural_violation` |
| M29 | the port reorders the frozen layer vocabulary | `rust::both_engines_report_the_same_layers_in_the_same_order`, `rust::every_committed_artifact_round_trips_and_verifies`, `rust::this_engine_reproduces_its_committed_capture`, `rust::verify_refuses_each_structural_violation` |
| M30 | the port's `has` stops distinguishing a present member from an absent one | `rust::every_committed_artifact_round_trips_and_verifies`, `rust::this_engine_reproduces_its_committed_capture`, `rust::verify_refuses_each_structural_violation` |
### checkpoint 2 — engine protocol (`p022-shadow-cp2`)

| | |
|---|---|
| mutations | **11** |
| caught | **11** |
| survived | **0** |
| compile errors (reported as such, never as "caught") | 0 |
| harness-honesty controls reporting zero failures | 1 |
| catches by layer | `python` 5, `rust-engine` 6, `rust-repro` 2 |
| mutations with exactly **one** catching layer | 9 — M32, M33, M34, M35, M37, M38, M39, M40, M41 |

| id | mutation | caught by |
|---|---|---|
| M31 | the reference stops declaring a projection on its layers | `python::artifact-golden`, `python::capture-verify` |
| M32 | the reference silently drops the foreign engine entries when regenerating | `python::artifact-golden` |
| M33 | the reference's verification accepts a partial projection that names no members | `python::structural-control` |
| M34 | the reference's verification accepts a 'full' projection that also names members | `python::structural-control` |
| M35 | the port declares its verdict layer FULL while it is at the checkpoint-4 projection | `rust-engine::this_engine_reproduces_its_committed_capture` |
| M36 | the port drops `column` from its verdict records while still claiming it | `rust-engine::a_partial_projection_names_exactly_the_members_it_carries`, `rust-engine::this_engine_reproduces_its_committed_capture` |
| M37 | the port stamps a refused layer with the 'produced' status | `rust-engine::this_engine_reproduces_its_committed_capture` |
| M38 | the port claims a surface version for the MOS dump, which has none | `rust-engine::this_engine_reproduces_its_committed_capture` |
| M39 | the port reports a typed-door refusal on one layer instead of all three | `rust-engine::this_engine_reproduces_its_committed_capture` |
| M40 | the port's verification stops rejecting a 'full' projection that names members | `rust-repro::verify_refuses_each_structural_violation` |
| M41 | the port's verification accepts an EMPTY reason on a partial projection | `rust-repro::verify_refuses_each_structural_violation` |
### checkpoint 3 — AnalysisTrace and stable-ID normalization (`p022-shadow-cp3`)

| | |
|---|---|
| mutations | **11** |
| caught | **11** |
| survived | **0** |
| compile errors (reported as such, never as "caught") | 0 |
| harness-honesty controls reporting zero failures | 1 |
| catches by layer | `python` 9, `rust-trace` 4, `rust-unit` 3 |
| mutations with exactly **one** catching layer | 7 — M42, M43, M45, M46, M48, M50, M51 |

| id | mutation | caught by |
|---|---|---|
| M42 | the reference derives a handle's stable id from the counter instead of the record's identity | `python::non-zero exit with no FAIL line` |
| M43 | the reference drops `line` from a handle's identity, fusing two facts on one line-distinct site | `python::trace-golden` |
| M44 | the reference stops disambiguating a repeated address | `python::trace-golden`, `python::trace-shape` |
| M45 | the reference declares the lowered layer's order canonical, licensing a sort | `python::trace-golden` |
| M46 | the reference declares the verdict layer's order canonical, hiding a tie-order defect | `python::trace-golden` |
| M47 | the reference narrows the minted-handle pattern so `loc_` names leak through unrewritten | `python::trace-golden`, `python::trace-normalization` |
| M48 | the reference gives a refused layer an empty step list AND drops its error | `python::trace-golden` |
| M49 | the port derives a handle's stable id from the counter instead of the record's identity | `rust-trace::a_mint_order_shift_moves_the_order_but_not_the_stable_ids`, `rust-trace::every_trace_golden_is_reproduced_byte_for_byte`, `rust-unit::trace::tests::a_fully_listed_document_normalizes` |
| M50 | the port declares the lowered layer's order canonical, licensing a sort | `rust-trace::every_trace_golden_is_reproduced_byte_for_byte` |
| M51 | the port stops asserting that the handle rewrite is total | `rust-unit::trace::tests::a_handle_reference_the_rename_cannot_reach_is_refused` |
| M52 | the port drops the mint kind from the handle record | `rust-trace::every_trace_golden_is_reproduced_byte_for_byte`, `rust-unit::trace::tests::a_fully_listed_document_normalizes` |
### checkpoint 4 — first-divergence reduction (`p022-shadow-cp4`)

| | |
|---|---|
| mutations | **11** |
| caught | **11** |
| survived | **0** |
| compile errors (reported as such, never as "caught") | 0 |
| harness-honesty controls reporting zero failures | 1 |
| catches by layer | `python` 9, `rust-reduce` 6 |
| mutations with exactly **one** catching layer | 9 — M54, M55, M56, M57, M58, M59, M60, M62, M63 |

| id | mutation | caught by |
|---|---|---|
| M53 | the reference widens the reduction scope to the verdict layer | `python::reduction-control`, `python::reduction-golden` |
| M54 | the reference reports the whole step instead of the minimal difference inside it | `python::reduction-control` |
| M55 | the reference stops noticing a step only one engine addresses | `python::non-zero exit with no FAIL line` |
| M56 | the reference stops noticing an ordering-only difference | `python::reduction-control` |
| M57 | the reference compares two engines' refusal TEXTS, manufacturing a divergence out of message vocabulary | `python::reduction-control` |
| M58 | the reference reports the LAST divergence instead of the first | `python::reduction-golden` |
| M59 | the reference stops distinguishing a key-ORDER difference from agreement | `python::reduction-control` |
| M60 | the reference carries the MOS document in `dump_summaries`' insertion order rather than its surface's | `python::artifact-golden` |
| M61 | the port widens the reduction scope to the verdict layer | `rust-reduce::every_reduction_golden_is_reproduced_byte_for_byte`, `rust-reduce::the_reducer_is_silent_on_unchanged_data_and_names_a_synthetic_divergence`, `rust-reduce::the_verdict_layer_is_refused_not_silently_skipped`, `rust-reduce::two_engines_that_both_refused_a_layer_agree` |
| M62 | the port compares two engines' refusal texts instead of the fact that both refused | `rust-reduce::two_engines_that_both_refused_a_layer_agree` |
| M63 | the port reports the last divergence instead of the first | `rust-reduce::every_reduction_golden_is_reproduced_byte_for_byte` |
