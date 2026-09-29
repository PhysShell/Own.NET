# P-037-X Stage 3 — real-world capability accounting of the six OSS cases (EXPLORATORY)

Research branch `research/p037-max-v1`. This stage adds **no code**: it classifies the six frozen
real cases (and their 22 census call sites) against the FROZEN P-037 vocabulary, as measured on the
Stage 2d tree (`0a7e184d`; binaries as recorded in the Stage 2d evidence). The evidence file is
`paper-eval/p037-max/stage3-real-cases-v1.json` in Own.NET-paperwork; every classification claim in
it is asserted against the Stage 2d reports before the file is written. #304 is frozen and unchanged;
nothing here is a production result. Wording: *P-037-X later recovered the guarded selection of 1 of
the 3 real precision witnesses (case 4) after exploratory driver extensions*; no verdict-level witness
is recovered.

## 1. The frozen rule and the classes (REPOSITORY FACT)

Prereg `stages[3]`: classes `SUPPORTED_EXACTLY / SUPPORTED_PARTIALLY / OUTSIDE_FROZEN_VOCABULARY /
SHAPE_ONLY / ANALYZER_SCOPE_LIMIT / UNKNOWN`; rule: *do not force case 2 (FinishSend) to pass; cases 4
and 5 are the plausible frozen-P-037 witnesses; a case blocked by record absence (R) is
ANALYZER_SCOPE_LIMIT even when the guard vocabulary would cover it*. The per-case predictions are the
prereg's `C_six_real[].stage3_prediction`; the per-site frozen actions are the historical callsite
ledger's `p037_frozen_site_action` (immutable). Nothing was re-run for this stage.

## 2. Result per case (MEASURED OBSERVATION + INFERENCE where marked)

| case | frozen prediction | measured on the 2d tree | class | held |
|---|---|---|---|---|
| 1 ImageHelpers.Outline | OUTSIDE_FROZEN_VOCABULARY + ANALYZER_SCOPE_LIMIT | no record for `Outline` or `Outline.Apply` (a `Bitmap` parameter is not owned-disposable for this extractor; no tracked local); no row at C01; 0 findings | **ANALYZER_SCOPE_LIMIT** (+ OUTSIDE: the site's guard is an instance property, G-V3/G-A1 join — INFERENCE) | yes |
| 2 HttpClient.FinishSend | OUTSIDE_FROZEN_VOCABULARY (frontier; Stage 4) | `FinishSend.cts = Split(disposeCts) [must, no]` EQUAL, `FinishSend.response = Uncond(no)`: the callee side is exact; C02–C05: the callers carry a record without a `cts` handle (the CTS is bound by a tuple deconstruction, never a leak candidate); C06: `SendAsync` is skipped (local function in its body), `Core` is not a class member; no row at any site; 0 findings | **OUTSIDE_FROZEN_VOCABULARY** (+ ANALYZER_SCOPE_LIMIT on the tuple-bound handle); summary-level SUPPORTED_EXACTLY | yes |
| 3 EcmaAssembly.CreateModule | SHAPE_ONLY | `CreateModule.peStream = Split(containsMetadata) [no, must]` EQUAL; C07 row EQUAL/unselected/plain = plain (the resource is a caller local: nothing to import the split into); C08 no record (inline `new MemoryStream(...)` argument); C09 collision | **SHAPE_ONLY** (+ ANALYZER_SCOPE_LIMIT at C08) | yes |
| 4 SymmetricCngTestHelpers.VerifyPersistedKey | SUPPORTED_EXACTLY at C12/C13 (NEG); C11 ANALYZER_SCOPE_LIMIT | `key = Split(disposeKey) [must, no]` EQUAL; C12 `:51` and C13 `:370`: APPLICATION_REFINEMENT, **neg → borrow** vs legacy plain; the two OWN051 are gone; no OWN009; C11: no record (the key is captured by an `Assert.Throws` lambda — the pre-existing closure-escape rule); flag on shows OWN001 at `:36`/`:355` (the kept key ends in `CngKey.Delete()`, unmodelled as a release: the pre-existing gap the prereg named) | **SUPPORTED_EXACTLY** for the guarded selection (+ ANALYZER_SCOPE_LIMIT at C11 and on the release model at the verdict level) | yes |
| 5 ArgumentSource.GetArguments | ANALYZER_SCOPE_LIMIT (R: iterator body unmodelled) | the iterator overload carries no record (`callee_unmodelled`); C16 `callee_sig`, the wrapper's `reader` `expression_form` → legacy `no` stands; C15 no record (inline `File.OpenText` argument); C17/C18 collisions; 0 findings | **ANALYZER_SCOPE_LIMIT** (the literal sites would be G-A1 selections — INFERENCE, not counted) | yes |
| 6 AuthHandshakeMessageHandlerTests.SendResponseAsync | SHAPE_ONLY + ANALYZER_SCOPE_LIMIT | `listener = Split(stopListenerAfterResponse) [must, no]` EQUAL; C19–C22: no record (using-declared listeners are never candidates; two sites in local functions); 0 findings | **SHAPE_ONLY** (+ ANALYZER_SCOPE_LIMIT) | yes |

Totals (primary): SUPPORTED_EXACTLY 1, OUTSIDE_FROZEN_VOCABULARY 1, SHAPE_ONLY 2, ANALYZER_SCOPE_LIMIT 2,
SUPPORTED_PARTIALLY 0, UNKNOWN 0; predictions held 6/6. Sites (17 resolved): SUPPORTED_EXACTLY 2 (C12,
C13), OUTSIDE_FROZEN_VOCABULARY 5 (C02–C06), SHAPE_ONLY 6 (C07, C08, C19–C22), ANALYZER_SCOPE_LIMIT 4
(C01, C11, C15, C16); 5 excluded name collisions (C09, C10, C14, C17, C18).

## 3. The three real precision witnesses (MEASURED OBSERVATION)

- **Case 4**: recovered at the guarded-selection level (the frozen NEG selection is realized at both
  literal sites; the false OWN009 of the observation census does not appear; the honest OWN051
  advisories are no longer needed). Not recovered at the verdict level: the two advisories become two
  OWN001 whose cause is `CngKey.Delete`, which the release model does not know — the gap the prereg
  named as independent of P-037-X and never to be fixed by an API-name rule.
- **Case 5**: blocked by record absence (R). The vocabulary would select at both literal sites; by the
  frozen rule that is an inference and the case is not counted.
- **Case 2**: blocked by the vocabulary (and by the tuple-bound handle). The callee summary is exact;
  no site can select because the guard is the caller local `disposeCts`, produced together with the
  CTS by one producer. This is the pre-registered Stage 4 frontier.

## 4. What Stage 4 has to decide (INFERENCE)

Case 2 needs a relational `(resource, ownsResource)` fact: produced by a tuple-returning producer
(`PrepareCancellationTokenSource`), bound by a deconstruction, consumed at one guarded call. Two things
stand between the frozen vocabulary and the site: the frontend never tracks a deconstruction-bound
handle, and G-A1 joins a caller-local guard. Stage 4's model — frozen in
`paper-eval/p037-max/stage4-relational-v1.json` before any code — must say which allowed form carries
the relation (producer-result / pair), how the carrier is transported, and what the three hostile
controls of the prereg measure. Nothing in Stages 1–3 pre-empts that answer.

## 5. Not claimed

That #304 is reopened; that case 4 is clean at the verdict level; that case 5 is recovered; that an
exact case-2 summary makes the witness recovered; any change to the frozen census classifications,
bug statuses, levels or decision.
