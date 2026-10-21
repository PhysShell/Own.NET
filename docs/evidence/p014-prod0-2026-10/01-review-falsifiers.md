# P-014 PROD0 — adversarial review falsifiers (pre-registration addendum)

Written 2026-10-21 15:12 +05, before any run.
- **Trigger.** The owner's code review of #423 at `f84943d`: `CI-PASS / CODE-REVIEW-HOLD / NO-MERGE`.
- **Budget.** 0.1 agent-day, counted from 15:11. STOP at 16:00.
- **Out of scope.** No sweep, no PROD1.

The original pre-registration (`00-preregistration.md`, `6ec551f`) is **not** changed. This file adds three
falsifiers against the binary built from `f84943d`'s sources.

| # | Fixture (own, synthetic, restored offline) | The claim under test | Falsified if |
|---|---|---|---|
| F-PROD0-1 | `net8.0`, no `<DefineConstants>`, a source with `#if NET8_0 … #else … #endif` | a unit whose measured preprocessor branch may differ from the SDK's is never `COMPLETE` | the sidecar says `COMPLETE` |
| F-PROD0-2 | `net8.0`, a source line `Console.WriteLine("/*probe:");` | text in an analysed source cannot stop the sidecar from being written | no sidecar is written, or the run fails |
| F-PROD0-3 | `net8.0`, one `.cs` made unreadable for the current user (ACL deny read) | `files.unreadable > 0` excludes `COMPLETE` | `unreadable > 0` together with `COMPLETE` |

## Consequence, fixed now

- **F-PROD0-1 confirmed.** This is a silent false claim of completeness, which falls under PROD0's original KILL
  ("silent false binding"). The report then records **`KILL-P014-PROD0`** for `f84943d`. That KILL stands even if a
  fix follows.
- **F-PROD0-2 or F-PROD0-3 confirmed.** Recorded as defects, not as a KILL by themselves.
- **Fix gate.** It is allowed only as a new, separately recorded gate: the fix plus F-PROD0-1, F-PROD0-2 and
  F-PROD0-3 re-run on the new head, plus all original G0–G3 checks re-run. The original PASS is not re-issued for
  `f84943d`. Any new head needs CI again.
- **Fix shape, fixed now (fail closed, no new semantics):**
  - any `#if`/`#elif` directive in a unit's sources becomes `SOURCE_SET_INCOMPLETE(preprocessor-conditional)`;
  - any unreadable source becomes `SOURCE_SET_INCOMPLETE(unreadable-source)`;
  - the research probe-marker parsing is removed from the production path (kept only behind an explicit harness
    switch, and bounds-checked).

  No defines and no implicit usings are applied (#407 stays separate).
