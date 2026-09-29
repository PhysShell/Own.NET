# P-037-X Stage 4 — relational ownership flags: the (resource, ownsResource) pair (EXPLORATORY)

Research branch `research/p037-max-v1`. Pre-registered in Own.NET-paperwork
`paper-eval/p037-max/stage4-relational-prereg-v1.json` (frozen before any code of this stage);
evidence in `paper-eval/p037-max/stage4-relational-v1.json`. #304 is frozen and unchanged; nothing
here is a production result; the Python reference, the kernel and the owning-factory table are
untouched. Wording: *P-037-X later made FinishSend's shape representable after exploratory
extensions; the frozen instance remains behind the owning-factory boundary.* Never "case 2 recovered".

## 1. The question and where it stood (REPOSITORY FACT)

Stage 3 left case 2 (`HttpClient.FinishSend`) OUTSIDE_FROZEN_VOCABULARY: the callee's contract is
exact (`FinishSend.cts = Split(disposeCts) [must, no]`), but every frozen site hands the resource
over together with a caller local produced by the same producer (`(cts, disposeCts, _) =
PrepareCancellationTokenSource(...)`), which G-A1 joins. The prereg's test: *does FinishSend become
representable, and at what cost*. Three independent blockers stood between the frozen vocabulary
and the site: the relation itself (vocabulary), the tuple-bound handle and the owned-slot gap of the
canonical carrier (carrier), and the producer's fresh acquire (`CreateLinkedTokenSource` is outside
the extractor's owning-factory table: an R boundary). The stage removes the first two generically
and leaves the third untouched by rule.

## 2. The abstraction (REPOSITORY FACT; six generic rules, none reads an API name)

Behind two opt-ins (`OWEN_P037X_RELATIONAL=1` for the emission, the existing `OWEN_P037X_GUARDED=1`
for the seam), with facts byte-identical otherwise:

- **R4-1 producer facts.** A pair/tuple-returning record carries `result_slots[]` (`resource` |
  `flag` | `other`) and every `return` carries `values[]` aligned with them (a tracked local's name,
  a boolean literal, or null; `"opaque"` for a non-literal return). A `new`-created candidate
  returned inside such a tuple is the D5.2 transfer out, not an escape.
- **R4-2 consumer facts.** A deconstruction of a first-party call is one `call` op with
  `results[]` by slot; the resource-slot designations are candidates the core decides on.
- **R4-3 sidecar.** A boolean local nothing assigns after its binding is `flag_var{name}`; the
  driver reads it as `opaque` everywhere but the witness match.
- **R4-4 relation.** Resource slot `i` is `fresh_iff(k)` when every literal return has
  (`values[i]` acquired in the body) ⇔ (`values[k] == true`), both polarities occur and no return
  is opaque. Always-fresh and never-fresh slots are deliberately no relation.
- **R4-5 site rule.** A local bound at a related slot is owned-iff its witness. A later call whose
  callee coordinate for that slot is `Split(h)` with finalized cells `(must, no)` and whose
  argument at ordinal `h` is `flag_var{witness}` discharges it: the core sees the handoff and the
  name is unmapped at a top-level site (a nested site keeps the map — the legacy kill-site
  restriction, because the map is shared by every branch). Every other site keeps the frozen
  reading (the collapse → INF-A5b untracking with OWN051).
- **R4-6 carrier.** An owned slot holding an untracked identifier is carried by that name; both
  engines apply the callee's contract per mapped argument and the filler is inert.

Bounded by construction: one relation value per result slot in {none, fresh_iff(k)}, one witness
name per handle, no state that grows with callers or paths; the kernel is untouched.

## 3. Results (MEASURED OBSERVATION)

| control (frozen) | off / facts-on+engine-off / Python | on | report | held |
|---|---|---|---|---|
| X4-P1 abstract shape | none | `OWN001` ×1 at `NeverCaller` (the owned path leaks) | `Produce` slot 0 `fresh_iff(1)`, slot 2 none; `Matched` (try/finally) and `MatchedPlain` RELATIONAL_DISCHARGE; `AlwaysCaller` must-discharged | yes |
| X4-P2 case-2 SHAPE TWIN | none | none | `PrepareCancellationTokenSource` slot 0 `fresh_iff(1)`; RELATIONAL_DISCHARGE at every `FinishSend` site of the four callers; `HandleFailure` a borrow | yes |
| X4-C1 unrelated flag | none | `OWN051` ×1 | witness `owns`, site carries `flag_var{other}`: no discharge | yes |
| X4-C2 reassigned flag | none | `OWN051` ×1 | the site's argument is opaque (unstable local): no discharge | yes |
| X4-C3 cross-association | none | `OWN051` ×2 (Crossed); Straight clean | Crossed: two witnessed, unmatched rows; Straight: two discharges | yes |
| X4-C4 polarity | none | `OWN051` ×1 | `(no, must)` is not the match | yes |
| X4-C5 owned-slot filler | none | none | `[first, r]` carried; `r` discharged; `first` never a handle | yes |

Every historical row (F3 8/8, the #380 family, the gallery anchor, the shapes, the B0 probes, the
B1 fixture, all 2b/2c/2d controls: 61 documents) is identical to Stage 2d in all three arms, with
facts byte-identical off vs on (no pair-returning producer anywhere in them). B1 acceptance and
every own-guarded test green (10 + 7 + 5 + 8). The frozen case 2 under the opt-in: the four
`FinishSend` sites gain rows (`var:cts`, EQUAL, unselected, no witness) and no relation forms —
`PrepareCancellationTokenSource` carries no record because its fresh CTS is a BCL factory outside
the owning-factory table; verdict 0 in every arm; the frozen instance stays ANALYZER_SCOPE_LIMIT.
Cases 1, 3, 4, 5, 6 unchanged in every arm.

Population: repository tree (82 files): facts byte-identical to Stage 2d in both arms, verdicts
identical (off 158 = Python, on 154 = Stage 2d on), 16 summary coordinates unchanged, no relation.
Corpus (137 documents): facts byte-identical to Stage 2d without the opt-in and byte-identical off vs on on every document (no pair-returning producer in the population); the same 8 documents move on-vs-off as in Stage 2d (the F3 refinements) and no other; class totals unchanged (summary EQUAL 33 / NGE 7; application REFINEMENT 8 / EQUAL 17 / NGE 49); no relation, no discharge.

Mutants (reader side, each rebuilt into the release engine): M1 (any flag at the guard ordinal matches) turns X4-C1 and X4-C3/Crossed clean and fails three acceptance tests; M2 (an opaque guard slot accepted when a witness exists) turns X4-C2 clean and fails its test; M3 (polarity ignored) turns X4-C4 clean and fails its test — each red at both levels, the reader restored to the recorded binaries (byte-identical digests after the rebuild).

## 4. Cost (MEASURED; the ledger has the full entry)

Handwritten lines against the Stage 3 tree: frontend +148/−2 (estimate +150..+220: within); core +413/−28 (own-guarded +275/−16, own-bridge +138/−12; estimate +180..+260: 1.59× the upper bound); joint +561 against +330..+480 (1.17×, within the frozen 1.5× criterion); tests and controls +215 (Rust) +43/−24 (Python harness) +386 (C# controls) +36/−1 (spec), fixtures/records +2248 (JSON, not code). New: 2 IR concepts (the positional result relation; the flag witness), 3 schema
fields + 1 sidecar argument kind, 1 relation value (`fresh_iff(k)`), 1 solver state (the witness
binding, with the lowering depth that scopes the unmap); 0 lattice dimensions, 0 transforms,
0 kernel lines, 0 Python lines.

## 5. Result

**KEEP** by the frozen decision rule — every control and expectation held, the mutants are red, the population did not move, no kernel or Python line changed, and the joint cost is within the criterion — with a recorded caveat: the core component alone is 1.59× its own estimate, so a per-component reading of the same rule says KEEP_BUT_COSTLY; this is the most expensive stage of the track, bought for one shape whose frozen instance still stands behind the owning-factory boundary. Stop condition G (complexity up sharply, instance-level real-witness coverage flat) is on the edge and is recorded as the boundary: any further step toward the frozen instance must buy an instance-level witness or the track stops on G. What the frozen instance still needs is one record — its fresh CTS is `CancellationTokenSource.CreateLinkedTokenSource`, outside the curated owning-factory set; extending that set for one row is forbidden here, and a generic factory rule is a production precision decision of the frontend, not a guard-vocabulary matter.

## 6. Not claimed

That #304 is reopened; that the frozen case 2 is recovered (the shape twin is not the frozen
input); parity with the opt-ins on; a false-transfer report on the not-owned path of a `must`
consumer (a stated limit); any change to the frozen census artefacts.
