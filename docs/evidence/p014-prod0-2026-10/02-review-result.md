# P-014 PROD0 — adversarial review result

**Verdict for `f84943d`: `KILL-P014-PROD0`.**
- **What it replaces.** The `PASS-P014-PROD0` in `REPORT.md` was issued on G0–G3. It did not survive the owner's
  code review.
- **Rule.** Fixed in `01-review-falsifiers.md`, commit `b446be4` (15:11:50 +05), before any run.
- **What is unchanged.** The original pre-registration and `REPORT.md` stay as they were, as the record of what
  was claimed.

## Runs [run, 15:13 +05]

- **Binary.** The extractor built from `f84943d`'s sources. `BindingCoverage.cs` and `Program.cs` were compared
  byte for byte with `git show f84943d:…`.
- **Fixtures.** `fixtures/F1`, `F2`, `F3`: `net8.0`, restored offline from the global packages folder.
- **Log.** `data/review_f84943d.log`.

| # | Observed | Claim | Result |
|---|---|---|---|
| F-PROD0-1 | `#if NET8_0 … #else … #endif`, no `<DefineConstants>`: exit 0, sidecar written, **`unit_status = COMPLETE`**, no source-set reason | a unit whose measured preprocessor branch may differ from the SDK's is never `COMPLETE` | **falsified.** The SDK defines `NET8_0` for `net8.0` [owner review, SDK behaviour]. The extractor parses with no defines, so it measured the `#else` branch and called the unit complete |
| F-PROD0-2 | a source line `System.Console.WriteLine("/*probe:");`: exit 0, **no sidecar**, stderr `ArgumentOutOfRangeException: length ('-56')` | text in an analysed source cannot stop the sidecar | **falsified.** The research probe-marker parsing in `Coverage.Measure` runs in production and does not check for the closing `*/` |
| F-PROD0-3 | `B.cs` denied read by ACL: exit 0, sidecar written, **`files.unreadable = 1` and `unit_status = COMPLETE`** | `unreadable > 0` excludes `COMPLETE` | **falsified.** `UnitStatus` does not read `Unreadable`, and the source-set scan skips the unreadable file silently |

**Not affected.** The facts document and the exit code. The flag still never changes them; F-PROD0-2's failure was
caught and reported on stderr, as designed. The defects are in what the sidecar **claims**.

## A further limit (from the review, by reading)

`foreign_binding` is computed against an allowlist built from the **same compilation's** references
(`Coverage.Allowed`). An assembly wrongly put into the manifest is therefore "allowed" by construction.
- The counter catches leaks **between source units**; the #422 guard self-test shows that.
- It does **not** independently prove that the manifest is right. The SDK-oracle comparisons (K3, K8a–c, K9, G0)
  are the evidence for the manifest; `foreign_binding = 0` is not.
- `REPORT.md` and #423 should not be read as claiming more.

## Proposed fix gate `FIX0` (not started; needs the owner's GO)

**Scope.** Fail-closed changes only. No defines and no implicit usings applied, no new semantics, no PROD1.

| Change | Rule |
|---|---|
| Preprocessor | any `#if`/`#elif` directive in a unit's sources, found when the source set is scanned (so it propagates to project-reference parents), gives `SOURCE_SET_INCOMPLETE(preprocessor-conditional)` |
| Unreadable source | a source the scan cannot read gives `SOURCE_SET_INCOMPLETE(unreadable-source)`; `Compile` also adds it if a later read fails |
| Probe markers | removed from the production path. `Coverage.Measure` records probes only when the harness passes an explicit switch, and then with a bounds check |
| `foreign_binding` | renamed in the report text only, as "cross-unit leak guard"; the sidecar field is unchanged. The manifest-correctness claim stays with the oracle checks |

**Acceptance (all on the new head):**
1. **The three falsifiers.**
   - F-PROD0-1: `SOURCE_SET_INCOMPLETE` with `preprocessor-conditional`.
   - F-PROD0-2: the sidecar is written.
   - F-PROD0-3: `SOURCE_SET_INCOMPLETE` with `unreadable-source`.
2. **G0–G3 re-run unchanged:**
   - facts byte-identical with `main`;
   - K1–K12 and the oracle fixtures;
   - P4/P5 not `COMPLETE`;
   - determinism;
   - cost within the original limits.
3. **Expected movements.** The only expected change in K-results is K7, whose `#if` now marks the unit
   `SOURCE_SET_INCOMPLETE`. Any other difference is a FAIL.
4. **CI** green again on the new head; `Owen: NEUTRAL` is the only accepted exception.

**Budget, proposed.** 0.25 agent-day. **KILL** if any of:
- a falsifier still holds;
- facts change;
- another unexpected K-result changes.
