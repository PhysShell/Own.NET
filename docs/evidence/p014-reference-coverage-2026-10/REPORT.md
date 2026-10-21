# P-014 reference-resolution coverage — report

**Pre-registered result: `GO-P014-BOUNDED-DESIGN`.** The GO has narrow content: the measured gain in Own.NET
diagnostics is small (§5).

**Owner decision on review: `ACCEPT-REFERENCE-COVERAGE-FINDING / HOLD-FORMAL-GO / NO-PRODUCTION`.** The formal GO is
held pending the verification in §8, which was done without a new experiment and without changing rules or
thresholds. §8 corrects one claim of this report, about package identity.

Rules: [`00-preregistration.md`](00-preregistration.md), commit `2e73767b` (04:43 +05; the "04:45" in its header is
my clock reading, and the commit time is the authoritative one). Own.NET `main` `c6e8a3c1`; extractor built offline
from that commit. Work: 04:37–04:52 +05 on 2026-10-21, inside the 0.25 agent-day budget.

No production, OwnIR, golden or CI change. No restore, build or MSBuild evaluation of third-party code, no package
download, no `MSBuildWorkspace`. Only artifacts already on disk were read.

## 1. The five answers

**1. How much does Own.NET suffer from wrong references?** At the binding level, a lot. In mode A (today's
compilation) only **32–48% of call sites bind in 4 of 5 projects**; P2 is the exception at 89%. Correct
project-specific references (mode B) recover 5–31% of all call sites in 4 projects. Even after B, 35–52% of calls in
P1, P3, P4 and P5 stay unbound.

**2. Which diagnostic classes lose coverage?**
- Event-subscription facts are hit hardest: `+=` sites that bind to an `IEventSymbol` go 10→35 in P1, 0→5 in P4 and
  11→48 in P5. The lost ones surface as OWN050 "cannot verify" advisories.
- Disposable fields and locals of external types are also lost: OWN001 on a WinForms dialog and on a
  `WindowsMediaController.MediaManager` field appear only with references.
- DI facts did not change in any project.

**3. How many bindings are recovered correctly?**
- 1,240 call sites, 1,028 type sites and 67 event sites are recovered by references and not by implicit usings
  (§3).
- A fixed sample of 50 recovered calls (10 per project) was read: **50/50 correct**.
- No site that bound in A lost its binding in B.
- 160 sites changed symbol. On reading, these are A bindings that were imprecise or **wrong for the target TFM**,
  not B errors (§3).

**4. Does recovery reach the existing diagnostics?** Yes, but thinly. Across 5 projects:
- 24 OWN050 disappear;
- 9 findings appear: 1 actionable TP, 2 minor/benign TPs, 6 FPs;
- 2 projects show no change at all.

The chain breaks mostly because Own.NET analyses consume only `+=`, `new` of disposables and DI registrations. Most
recovered calls (logging, WPF/Avalonia API, System.CommandLine) feed no analysis (§5).

**5. What is cheapest?**
- **Build-free resolution from existing `obj/project.assets.json`**, plus the TFM reference packs and
  package/framework name-conflict resolution. It recovered the bindings without any build.
- **Ready-made compilation artifacts** (`bin/`, `obj/ref`, `.rsp`, binlog): none of the five projects had them, so
  this cannot be measured and is unavailable in practice for scanned repositories.
- **A full project system** (`MSBuildWorkspace`) is not needed for what was measured.

Two limits of the assets route:
- it works only where a restore has already happened;
- for P1, the TFM can only be approximated: no 9.0 reference pack exists on this host. Package identity, first
  reported as unprovable, is confirmed in §8.2.

A separate, comparably large and cheaper lever is the **source set**: SDK implicit usings recover 172 calls in P3,
330 in P5 and 20 in P4 on their own (mode C).

## 2. Inputs and what was checked in code

The current-state claims are confirmed in `main` (pre-registration §0):
- one `CSharpCompilation("own", …)`;
- the framework set is the TPA of the `net8.0` extractor process, i.e. the 8.0.31 implementation assemblies;
- `--ref-dir` and `bin/` are loaded recursively, first filename wins;
- no MSBuild evaluation;
- no binding metric;
- default parse options, so no defines and no implicit usings.

| # | Project @ SHA | TFM measured | B completeness |
|---|---|---|---|
| P1 | Flow.Launcher `Flow.Launcher.csproj` @ `2efbf865` (WPF) | net9.0-windows… | **TFM-APPROX** (no 9.0 pack, used 10.0.12); 70 packages with compile assets missing from the cache; 47 package assets skipped as framework-name conflicts |
| P2 | git-credential-manager `Core.csproj` @ `e66693fa` | net10.0 | 20 packages missing |
| P3 | nats.net `NATS.Client.JetStream.csproj` @ `176e52bc` (multi-TFM) | net8.0 | 2 packages missing |
| P4 | BB84.IPTV `BB84.IPTV.M3U.Editor.csproj` @ `e9ab4f28` (desktop) | net10.0 | complete |
| P5 | FluentFlyout `FluentFlyout.csproj` @ `911dfda6` (WPF) | net10.0-windows10.0.22000.0 | complete, including Windows SDK projection 10.0.22000.57 |

**Corrected in §8.2.** The original text here said every B package was an `APPROXIMATION` because the assets'
`sha512` differs from the cache's `.nupkg.sha512`. That compared the wrong fields. The assets' value equals the
cache's recorded content hash (`.nupkg.metadata`) for all 231 packages present, so their identity is confirmed.
`APPROXIMATION` remains for P1's TFM, for the packages missing in P1–P3, and for B-ext (§5).

P1–P3's assets were written by CodeQL buildless extraction on 2026-10-17, before the D13 isolation, and their
package folders are gone.

Reference manifests with per-DLL SHA-256 prefixes are in `data/manifest_B_P*.tsv`, and the overview is in
`data/manifest.json`.

## 3. R0–R2: binding coverage (`data/r0_r1_summary_P*.json`, `data/r2_summary.tsv`)

| Project | Calls bound A / B / C (of all) | Recovered by references | Fixed by usings only | Types A→B | `+=` events A→B |
|---|---|---|---|---|---|
| P1 | 925 / 1373 / 925 (of 2844) | **448 (15.8%)** | 0 (ImplicitUsings off) | 2081→2575 | 10→35 |
| P2 | 3401 / 3462 / 3401 (of 3820) | 61 (1.6%) — below threshold | 0 | 5718→5757 | 6→6 |
| P3 | 353 / 396 / 525 (of 839) | **43 (5.1%)** | 172 | 1293→1323 | 0→0 |
| P4 | 169 / 228 / 189 (of 353) | **59 (16.7%)** | 20 | 267→329 | 0→5 |
| P5 | 643 / 1272 / 973 (of 2003) | **629 (31.4%)** | 330 | 1788→2191 | 11→48 |

Compiler errors in A versus B (CS0246+CS0234+CS0103+CS1061):

| Project | A | B |
|---|---|---|
| P1 | 3,429 | 2,106 |
| P4 | 385 | 219 |
| P5 | 2,388 | 1,064 |

These numbers are context only; they were not used for the verdict.

**Correctness.** The sample (`data/r2_review_sample.tsv`) was read site by site. Each recovered call binds into the
library the file imports: WPF `PresentationCore`/`PresentationFramework`, Microsoft.Extensions.DI/Logging/
Configuration/Hosting, System.CommandLine, Avalonia, NLog, NAudio, Windows SDK projections. Some recoveries are
cascades and are also correct, e.g. `window.GetType()` once `window`'s type is known, or an overload that resolves
once its argument types are known. The result is 10/10 in each of P1, P3, P4 and P5, and 10/10 in P2. "Correct"
means the symbol and assembly agree with the code's imports and types. It is not checked against a real build.

**Symbol changes** (`data/r2_symbol_changed.tsv`, 160 sites):
- 116 are A bindings with error-typed parts made precise by B: 112 generic arguments or types that became known, and
  4 arrays whose element type was an error type that A counted as "resolved".
- The other 44 keep the method name but change the signature. Most are parameter types that became known.
- **The TFM effect.** In P1 `TimeSpan.FromHours(5)` binds `FromHours(double)` in A (.NET 8 TPA) and
  `FromHours(int)` in B. That overload exists from .NET 9, and P1 targets net9. **A silently binds an overload the
  project does not use.**
- No change was judged `RECOVERED_WRONG`.

**Controls** (`data/controls/`):

| Control | Result |
|---|---|
| K1 consistent | no change |
| K2 same filename, different identity | **A's first-filename-wins loads v1, so `V2Only()` is unresolved in A**; B, with the manifest-selected v2, resolves it |
| K3 TFM | B uses the selected TFM |
| K5 | `event` vs `int` field `+=` distinguished in both modes |
| K6 | missing type stays unresolved; nothing invented |
| K7 | both modes see the `#else` branch (no defines): a source-set limit |
| **K4** | two `Dup.T` in one compilation produce no "ambiguous": Roslyn binds the first one, in both modes. Definition conflicts are invisible to the single-compilation model, the extractor's included. Since A == B, no false recovery is claimed |

## 4. Instrument corrections made before scoring (disclosed)

1. **Framework/package name conflicts.** B initially referenced package compile assets with the same names as
   framework reference-pack assemblies. In P1 this gave 11,574 × CS0518 and 771 × CS0433. The pre-registration
   forbids that replacement, so such assets are now skipped (P1 47, P2 3, P4 1) and counted. The first output is
   kept as `proj-v1` in the work folder only. P5 still shows 59 × CS0433 between two framework references, which
   is not resolved.
2. **Site keys.** Nested invocations starting at the same position overwrote each other, which undercounted calls.
   The key now includes the span length, and all projects and controls were re-measured.
3. **Path patterns.** Two path bugs in my own driver were fixed: the `out/obj/<Project>` assets layout, and the
   Windows SDK projection version match.

No threshold, input or rule changed.

## 5. R3: does it reach Own.NET? (`data/r3/r3_P*.json`)

The unchanged extractor was run with `--flow-locals --stats`, then the Python reference core. No Rust core is built on
this host, so the Rust core was not run.

- **A-ext:** as shipped.
- **B-ext:** `OWN_EXTRA_REF_DIRS` = B's framework packs, plus `--ref-dir` per package compile folder. The TPA stays
  first, so B-ext is the most today's extractor can be given.

| Project | OWN050 A→B | OWN001 A→B | Other | Facts |
|---|---|---|---|---|
| P1 | 27→16 | 5→8 | — | flow functions 5→6, flow acquires 2→3 |
| P2 | 0→0 | 15→15 | — | unchanged |
| P3 | 5→5 | — | — | unchanged |
| P4 | 1→1 | 6→9 | — | unchanged |
| P5 | 15→2 | 1→3 | OWN014 0→1 | flow functions 1→5 |

Triage of the 9 new findings (code read):

| Finding | Verdict |
|---|---|
| P5 OWN014 `SettingsManager.Current.PropertyChanged` (`SettingsWindow.xaml.cs:213`): a closeable window's handler captures `RootNavigation`/`Dispatcher` on a static singleton's event, no unsubscribe (`Closed` only nulls `instance`) | **TP, actionable** |
| P5 OWN001 field `mediaManager` (`MainWindow.xaml.cs:48`), never disposed; cleanup only unsubscribes | TP-benign: the window is app-lived |
| P1 OWN001 WinForms `OpenFileDialog dlg` not disposed (`SettingsPaneGeneralViewModel.cs:360`) | TP-minor (`using`) |
| P1 `ProgressBar.IsVisibleChanged` (own XAML child), P1 `link.Click` (local hyperlink in own document), P5 `window.SourceInitialized` (own window), P4 `dialog.Closed` (local dialog) | FP: same lifetime |
| P4 `desktop.Startup` / `desktop.Exit` | FP: app-lived source |

**Where the chain `reference → symbol → fact → diagnostic` breaks:**
- **symbol → fact.** Of about 1,240 recovered calls, only a handful are `+=` on events or `new` of disposables. The
  rest have no consuming analysis, by design.
- **fact → diagnostic.** The newly visible subscriptions fall mostly into the known co-lifetime FP class (D11/D13
  R5). That precision problem is not a reference problem.
- **#382 (call lowering).** Not separately triggered here. P5's flow functions 1→5 show that newly typed
  disposable locals do enter the flow pass. Whether their calls are then lowered to guesses was not measured.

## 6. Verdict against the thresholds

| Criterion | Result |
|---|---|
| 1. ≥ 2 projects with reference-caused loss ≥ 5% of calls and ≥ 20 sites | **yes: P1, P3, P4, P5** (P2 no) |
| 2. ≥ 9/10 sampled recoveries correct in those projects; K1–K6 pass | **yes**: 10/10 each; controls pass. K4 shows the conflict blind spot, but no false recovery |
| 3. ≥ 1 useful change in OwnIR facts or findings | **yes**: P5 OWN014 TP; OWN050 replaced by verified facts (P5 `mediaManager` events now seen unsubscribed) |
| 4. B from on-disk artifacts, no forbidden action, bounded cost without MSBuildWorkspace | **yes**: needs an existing restore; package identity confirmed (§8.2); P1's TFM approximate (§8.3) |

So **`GO-P014-BOUNDED-DESIGN`**. What the GO does and does not support:
- The hidden-limit hypothesis is confirmed **at the binding level**. Own.NET today understands roughly a third to a
  half of the calls in 4 of these 5 projects, and its finding counts do not show that.
- The **diagnostic** payoff of fixing references alone is small: +1 actionable TP and 2 minor ones against 6 FPs,
  over 5 projects. Better references mainly convert OWN050 into checked facts.
- A design should be scoped as **reading existing `project.assets.json`**: select one TFM, add the reference packs,
  apply framework-first conflict resolution, and report binding coverage. It should be measured on implicit usings
  too, which are a source-set fix outside P-014's reference scope and an earlier owner decision.

## 8. Verification after owner review (no new experiment, no rule or threshold change)

### 8.1 K4, from the frozen instrument's own output

The K4 `summary.json` written by the scoring build of the instrument (04:47; DLL sha256 `c67a6be1…`) is now
committed as `data/controls/K4.summary.json`. Before, only `sites.tsv` was committed. It records:

| Mode | K4 compiler errors |
|---|---|
| A | `CS0101: 1`, plus the 12 × `CS0009` every A run has (12 native DLLs in the TPA folder) |
| B | `CS0101: 1` |
| C | `CS0101: 1` |

CS0101 is "the namespace already contains a definition". The K4 sources contain exactly one duplicated name,
`Dup.T` in `p1/a.cs` and `p2/b.cs`, so this error is the duplicate definition. The diagnostic message itself was
not saved; this attribution is by elimination.

At the same time, the call site `new Dup.T().One()` is `resolved` in every mode: Roslyn binds the first
declaration.

Against the pre-registered K4 ("recorded as ambiguous/conflict, never `RECOVERED_CORRECT`"):
- **Recorded as a conflict:** yes, at **compilation level** (CS0101 in all modes).
- **Never `RECOVERED_CORRECT`:** yes, because A == B and no recovery is claimed.
- **Not recorded at site level:** the per-site binding silently picks the first definition.

Whether compilation-level registration satisfies K4 is the owner's call. The facts above do not change with it.
All seven control summaries are now in `data/controls/K*.summary.json`.

### 8.2 NuGet SHA-512 comparison

The original check (§2) compared the assets' `libraries[*].sha512` with the cache's `<id>.<ver>.nupkg.sha512` file.
Re-checked without replacing any hash. For every package of the five projects that has a `.nupkg` in the cache, I
computed SHA-512 (base64) of the `.nupkg` file myself:

| Comparison | P1 | P2 | P3 | P4 | P5 |
|---|---|---|---|---|---|
| packages present (`.nupkg` on disk) | 89 | 17 | 19 | 87 | 19 |
| cache `.nupkg.sha512` == my hash of the `.nupkg` | 89 | 17 | 19 | 87 | 19 |
| assets `sha512` == my hash of the `.nupkg` | 0 | 0 | 0 | 0 | 0 |
| assets `sha512` == cache `.nupkg.metadata` `contentHash` | **89** | **17** | **19** | **87** | **19** |
| packages missing from the cache | 76 | 20 | 9 | 0 | 0 |

- The assets' `sha512` is NuGet's package content hash, the same value NuGet records in `.nupkg.metadata`. It is
  not the hash of the `.nupkg` file, so my original comparison was wrong. All 231 present packages match their
  assets entry, and **package identity is confirmed**, not approximate.
- **Not checked by me:** why the content hash and the file hash differ. Package signatures are the likely reason.
- **Package sources** (`.nupkg.metadata` `source`): P4 and P5 are all, or all but one, from nuget.org. For P1–P3,
  46, 2 and 2 packages came from another source. The source addresses are not published here (D13). Identical
  content hashes make the content the same whatever the source.

### 8.3 Exact versus approximate projects

| Project | TFM pack | Packages | Calls recovered by references | Status |
|---|---|---|---|---|
| **P4** | exact (10.0.12) | all present, identity confirmed | 59 (16.7%) | **exact** |
| **P5** | exact (10.0.12, Windows SDK 10.0.22000.57) | all present, identity confirmed | 629 (31.4%) | **exact** |
| P3 | exact (8.0.31) | 2 with compile assets missing | 43 (5.1%) | partial packages |
| P1 | **10.0.12 for net9** (`UNAVAILABLE_UNDER_D13`: no 9.0 pack) | 70 with compile assets missing | 448 (15.8%) | TFM-approximate |
| P2 | exact (10.0.12) | 20 with compile assets missing | 61 (1.6%) | below threshold |

- **Exact projects only.** Criterion 1 (≥ 2 projects with ≥ 5% and ≥ 20 sites) is met by **P4 and P5**.
- **P1's `TimeSpan.FromHours(int)`.** It is the B binding against the 10.0 pack. That `(int)` is the right overload
  for P1's net9 target is **not verified**: it needs the exact 9.0 reference pack, which is not available. The
  confirmed fact is narrower: A binds to an overload chosen from the .NET 8 implementation, not from the project's
  target.

### 8.4 What the sample does and does not show

- **The sample.** 50 of 1,240 reference-recovered calls were read, 10 per project, seed `20261021`, and 50/50 were
  correct.
- **What it supports.** Under a Clopper–Pearson 95% bound, about ≥ 93% correctness over all recovered calls, and
  about ≥ 69% per project from 10/10.
- **What it does not prove.** It does not show that every one of the 1,240 calls, the 1,028 type sites or the 67
  event sites is correct.
- **The 160 changed symbols** were classified **automatically** (116 precision gains, 44 signature changes). Only
  16 were read (12 signature changes and 4 error-element arrays), so the "no `RECOVERED_WRONG`" statement covers
  those 16.

### 8.5 R2 and R3 use different framework selection

R2's B compiles against the target TFM's reference packs. R3's B-ext keeps the extractor's .NET 8.0.31 TPA first,
and adds packs and packages only for names the TPA lacks. The R3 diagnostic changes therefore come from a weaker
reference set than R2's binding numbers, and the two sets of numbers are not one mechanism.

`project.assets.json` describes restored dependencies. It is not a substitute for compiler reference resolution:
- no project references are built;
- no MSBuild-time items, properties or analyzers are applied;
- no conflict resolution is done beyond the framework-name rule used here.

### 8.6 Effect on the verdict

- Criteria 1, 3 and 4 hold. Criterion 1 holds on the exact projects alone (P4, P5), and criterion 4 now holds
  without the identity caveat.
- Criterion 2's controls hold, with K4's conflict recorded at compilation level only (§8.1).
- The pre-registered result stays `GO-P014-BOUNDED-DESIGN`. The owner's `HOLD-FORMAL-GO` applies until the K4
  reading is decided.

## 9. Files

- `00-preregistration.md`, `REPORT.md`
- `instrument/` (Roslyn binding instrument), `controls/make_controls.py`
- `scripts/build_modes.py` (A/B/C inputs), `scripts/classify.py` (R2), `scripts/run_r3.py` (R3)
- `data/`: `manifest.json`, `manifest_B_P*.tsv`, `r0_r1_summary_P*.json`, `r2_summary.tsv`, `r2_review_sample.tsv`,
  `r2_symbol_changed.tsv`, `r3/`, `controls/`. Local paths are replaced by `<research>`, `<work>`, `<nuget>` and
  `<dotnet>`. Only short expression excerpts appear; no third-party source files, DLLs or packages are committed.
