# N3 bounded pilot, gates G1–G4 — report

**Result: `KILL-N3-PILOT` at G3.** On the pre-registered independent sample the PoC gives 0 product warnings, fewer
than the required 5 ("not enough data for a GO"). The sample is not widened. G1 and G2 passed; G4 is not run.

Rules: [`01-preregistration-g1-g4.md`](01-preregistration-g1-g4.md), committed in `797f74c5` before any PoC code.
Authority: `ACCEPT-PASS-G0 / GO-G1-PREREG-AND-BOUNDED-EXECUTION / NO-PRODUCTION`. Time used: 20:23–21:00 +05 on
2026-10-20, inside the one agent-day budget.

Nothing in production, OwnIR, CI or goldens was touched. Third-party code was parsed only. Trees were exported with
`git archive` from shallow fetches; nothing was restored or built (D13 isolation rule). The PoC itself was built
outside `source/repos` with a nuget.org-only config and no package reference.

## 1. Gate summary

| Gate | Verdict | Evidence |
|---|---|---|
| G1 tiny PoC | **PASS** | 3/3 required pairs report on the buggy tree at a line the fix changes. Each fixed tree is silent on the touched code (§3) |
| G2 negative controls | **PASS** | C1–C15 silent, and the 15 positive samples reported, on PoC v2 (`data/g1/controls_v2.tsv`) |
| G3 independent precision | **KILL** | 27 repositories, **0** warnings (§4) |
| G4 practical yield | not run | stopped at G3 |

## 2. One implementation fix between the first and the scored run (disclosed)

PoC v1 (`6a44d991`) was correct on the control file. On DotNetCloud#43 it produced 3 extra D3b warnings, from two
departures from §3 of the pre-registration:

- it accepted a call to a `void` same-class method as D3b, while §3 defines D3b as a discarded Task call
  (`_ = MAsync(…)`);
- it took an `await` inside a nested lambda as the callee's first `await`.

v2 (`602d4a89`) applies §3 as written and also records the capture line. No ownership or detachment rule changed.
Control C15 covers this case; the pre-registration allows adding controls after the first run. v1 output is kept in
`data/g1/warnings_v1.tsv`.

One input mistake was also corrected before scoring. The buggy tree was first taken as the merge commit's parent.
For mars-vista-api#26, which was rebase-merged from several commits, that parent already contains the fix. The
scored run uses the PR's `base.sha`, and `base.sha` is an ancestor of the fix commit in all six pairs
(`data/g1/pairs.tsv`).

## 3. G1 — pairs

Each warning's call line or capture line was checked against the fix diff with
[`scripts/g1_touched.py`](scripts/g1_touched.py). The result is `data/g1/touched_v2.tsv`.

| Pair | Buggy tree | Fixed tree |
|---|---|---|
| mars-vista-api#26 (required) | `UsageTrackingMiddleware.cs:63` S1×D3b: `_ = TrackUsageAsync(context, …)`, with `context` used after the callee's first `await`. Line removed by the fix | silent on the touched file |
| DotNetCloud#43 (required) | `VideoIndexingCallback.cs:366` S3×D1: discarded `Task.Run` using `_seriesService`, capture line 371 removed by the fix. Holder `VideoIndexingCallback` and `IVideoSeriesService` are both proven scoped (R3, S3) | silent on the touched file |
| DFY-BE#35 (required) | `AuthController.cs:70` S3×D3a: `_ = _notificationService.NotifyAdminsAsync(…)`, line changed by the fix | 0 warnings |
| Vendorea#49 (reported only) | `AdminFtpIngestionController.cs:272` S4×D1, capture line 276 changed by the fix | 0 warnings |
| microting#1669 (reported only) | silent: the holder `ContentHandoverService` is registered transient, which is not request-bound in this slice | silent |
| escalated#162 (reported only) | silent: `WebhookDispatcher` is scoped, but `EscalatedDbContext` is registered by the consuming app, not in the repository, so S2 is unproven | silent |

Warnings in the pair repositories outside the fixed code were not scored, and are recorded as possible further
instances only. They are present on both trees:

- mars-vista `UserApiKeyAuthenticationMiddleware.cs:153`: `context.RequestServices` inside a discarded `Task.Run`;
- DotNetCloud `VideoController.cs:838` (D3a) and `:1462` (D1).

## 4. G3 — the independent sample

- **Input.** The 28 pre-registered repositories at their pinned SHAs, with saved facts from the `e7d33e33`
  extractor. dnSpy has no facts, because the extractor crashed on it in D11 (N13), so 27 were scanned.
- **Result.** 0 warnings in 27 repositories (`data/g3/summary.tsv`, `data/g3/run.log`). The PoC saw 1,929
  request-bound types and only 7 detached sites, all of them without a proven scope-owned use.
- **Independent check that 0 is not a blind spot.** A plain grep was run for statement-level `Task.Run` /
  `Task.Factory.StartNew`, `_ = …Async(…)` and `QueueBackgroundWorkItem` in non-test paths
  (`data/g3/crosscheck_grep.tsv`).
  - It found 526 sites. 13 are in types whose name or base contains `Controller`, `PageModel` or `Hub`.
  - Of those, the real ASP.NET controllers are Jackett `ServerConfigurationController` (a static helper), Radarr
    `SystemController` (`_lifecycleService`) and Jellyfin `LibraryStructureController`. Jellyfin's
    `ILibraryManager` and `ILibraryMonitor` are `AddSingleton` (`ApplicationHost.cs:577`, `:583`).
  - The rest match by name only: Duplicati's `Controller` classes and a WPF gallery.
  - None captures a scope-owned object, so the PoC's silence matches the code.

The sample is mostly libraries. Only about 7 of the 27 are request-serving web applications: OrchardCore, eShop,
bitwarden, nopCommerce, Jellyfin, Radarr and Jackett. This was known when the sample was fixed, and the
pre-registration forbids widening it after the run.

## 5. What this does and does not show

Confirmed:
- The narrow slice (§2/§3) finds the three required real defects and stays silent on their fixes and on 15
  negative controls.
- Mature code in the fixed sample contains no instance of the slice: 0 by the PoC and 0 by an independent grep.

Inference: the class recurs in young applications, as Phase 0 found (7 of 8 repos with 0–4 stars). Here it was not
observed in mature code, which matches what D11 recorded for C10 (mature-code yield 0).

Not shown:
- Precision is unmeasured; there were no warnings to measure it on.
- Yield on a sample of mature **web applications** only was not tested.
- The silent S-unknown cases were not counted by kind: transient `IDisposable`, consumer-registered `DbContext`,
  transient holders, factory lambdas.

## 6. Files

- [`01-preregistration-g1-g4.md`](01-preregistration-g1-g4.md): the rules.
- [`controls/N3NegativeControls.cs`](controls/N3NegativeControls.cs): controls C1–C15 and positive samples.
- [`poc/`](poc/): the PoC (Roslyn, no package reference).
- [`scripts/n3_run.py`](scripts/n3_run.py): the runner.
- [`scripts/g1_touched.py`](scripts/g1_touched.py): the diff check.
- `data/g1/`: pairs with SHAs, v1 and v2 warnings, the diff check and control output.
- `data/g3/`: per-repository summary, run log and the grep cross-check.
