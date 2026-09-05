<!-- GENERATED FILE — do not edit by hand.
     Regenerate: python scripts/render_checkpoint_status.py --write
     Checked by: tests/test_generated_docs.py (a stale copy is a red build).
     Every figure below is read out of committed evidence; none is typed. -->

# P-022 step 7a — shadow-mode infrastructure, checkpoint 1: census

**Infrastructure for shadow mode, not shadow mode.** Nothing measured here
compares two engines' end diagnostics; that comparison is #260's acceptance
and is blocked on #259 (cp5 and 4b). Nothing here is a parity claim either.

## The measured set

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
checked fact rather than an assumption.

| surface | count |
|---|---|
| documents captured and digest-pinned | 80 |
| tamper controls (one changed character per document, refusal required) | 80 |
| documents both engines must REFUSE to name (`domain_refusals`) | 6 |
| reproduction artifacts committed and replayed byte-for-byte | 8 |
| layer envelopes carried by those artifacts — produced | 21 |
| layer envelopes carried by those artifacts — refused | 3 |
| structural negative controls on `verify` (each side) | 12 |
| value-level domain backstop controls | 5 |

## Divergence classification over the measured set

**Python-only 0 / Rust-only 0 / Changed 0 / Ordering-only n/a / Unexplained 0.**

These are enforced by a gate, not counted by this generator: the port asserts
per-document equality of the canonical identity and byte-exact equality of
every committed artifact, so a non-zero counter is not representable as a
passing build. *Ordering-only* is **not applicable** at this layer and is
named rather than reported as a zero that would mean something else — the
canonical form sorts by construction, so there is no ordered output being
compared yet. The gates:

- `own-shadow/tests/repro.rs::a_changed_byte_in_the_embedded_document_is_refused`
- `own-shadow/tests/repro.rs::every_committed_artifact_round_trips_and_verifies`
- `own-shadow/tests/repro.rs::every_declared_unnameable_document_is_refused`
- `own-shadow/tests/repro.rs::every_shared_document_hashes_to_the_recorded_digest`
- `own-shadow/tests/repro.rs::the_canonical_form_ignores_only_insignificant_text_formatting`
- `own-shadow/tests/repro.rs::values_outside_the_canonical_domain_are_refused_at_parse`

## The unmeasured set, named

- **End diagnostics compared as an acceptance surface** — #260's acceptance,
  blocked by #259 (cp5 and 4b). Not attempted, not approximated.
- **The engine protocol** (how the port fills its own `engines[]` entry), the
  **`AnalysisTrace` schema** (#269) and **stable-ID normalization**, and
  **first-divergence reduction** over the lowered/MOS layers — the remaining
  step-7a checkpoints. The artifact format has the slots; one engine fills
  them today.
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

## Mutation campaign

Definition: `docs/notes/p022-shadow-infra-checkpoint1-data/mutations.json`.
Recorded result: `.../campaign.json`. Both layers run for every mutation
(P-022 discipline 3: no fail-fast), and every mutation edits a **production**
surface (discipline 2).

| | |
|---|---|
| mutations | **30** |
| caught | **30** |
| survived | **0** |
| compile errors (reported as such, never as "caught") | 0 |
| harness-honesty controls reporting zero failures | 1 |
| catches attributed to the reference harness | 19 |
| catches attributed to the port's suite | 30 |
| mutations with exactly **one** catching layer | 15 |

A rule with a single catcher is a rule with a single control: M04, M05, M06, M07, M08, M09, M10, M11, M12, M14, M15, M21, M24, M25, M26.

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
| M16 | the port's canonical form stops sorting object keys | `rust::every_committed_artifact_round_trips_and_verifies`, `rust::every_shared_document_hashes_to_the_recorded_digest`, `rust::verify_refuses_each_structural_violation` |
| M17 | the port escapes U+007F, which the reference emits raw | `rust::every_committed_artifact_round_trips_and_verifies`, `rust::every_shared_document_hashes_to_the_recorded_digest` |
| M18 | the port escapes control code points with uppercase hex | `rust::every_committed_artifact_round_trips_and_verifies`, `rust::every_shared_document_hashes_to_the_recorded_digest` |
| M19 | the port renders the artifact with a different indent width | `rust::every_committed_artifact_round_trips_and_verifies`, `rust::the_canonical_form_ignores_only_insignificant_text_formatting` |
| M20 | the port renders an artifact's objects in sorted rather than document order | `rust::every_committed_artifact_round_trips_and_verifies`, `rust::the_canonical_form_ignores_only_insignificant_text_formatting` |
| M21 | the port resolves a duplicate key first-wins instead of last-wins | `rust::the_canonical_form_ignores_only_insignificant_text_formatting` |
| M22 | the port wraps an out-of-i64 integer instead of refusing it | `rust::every_declared_unnameable_document_is_refused`, `rust::values_outside_the_canonical_domain_are_refused_at_parse` |
| M23 | the port accepts a float as an integer instead of refusing it | `rust::every_declared_unnameable_document_is_refused`, `rust::values_outside_the_canonical_domain_are_refused_at_parse` |
| M24 | the port's verification stops comparing the recomputed digest | `rust::a_changed_byte_in_the_embedded_document_is_refused` |
| M25 | the port's verification stops checking the frozen layer order | `rust::verify_refuses_each_structural_violation` |
| M26 | the port's verification stops checking the frozen engine order | `rust::verify_refuses_each_structural_violation` |
| M27 | the port renders the digest with uppercase hex | `rust::every_committed_artifact_round_trips_and_verifies`, `rust::every_shared_document_hashes_to_the_recorded_digest`, `rust::verify_refuses_each_structural_violation` |
| M28 | the port hashes the RENDERING form instead of the canonical form | `rust::every_committed_artifact_round_trips_and_verifies`, `rust::every_shared_document_hashes_to_the_recorded_digest`, `rust::the_canonical_form_ignores_only_insignificant_text_formatting`, `rust::verify_refuses_each_structural_violation` |
| M29 | the port reorders the frozen layer vocabulary | `rust::every_committed_artifact_round_trips_and_verifies`, `rust::verify_refuses_each_structural_violation` |
| M30 | the port's `has` stops distinguishing a present member from an absent one | `rust::every_committed_artifact_round_trips_and_verifies`, `rust::verify_refuses_each_structural_violation` |
