# Full post-batch oracle remeasure — 2026-07-12

Follow-up to [`oracle-sweep-2026-07-10.md`](oracle-sweep-2026-07-10.md) (issue
\#201), [`oracle-sweep-rerun-2026-07-11.md`](oracle-sweep-rerun-2026-07-11.md),
and [`precision-remeasure-2026-07-11.md`](precision-remeasure-2026-07-11.md).
Those covered partial slices of the follow-up batch (#218/#220/#222/#223/#224,
then #225/#228). This note remeasures all **5** pinned targets on current
`main` after the **complete** batch — #218, #219, #220, #222, #223, #224,
\#227, #228, #229 — and the #238 soundness regression + #240 hotfix.

## Method

- **Targets and pinned commits** — same as the established sweep, reused
  verbatim (no re-resolution against upstream HEAD): ShareX `0df9ca4`,
  MahApps.Metro `72099e3`, MaterialDesignInXamlToolkit `ef3a5ea`, AvalonEdit
  `ed0bd14`, ClosedXML `4e89dce`. All five were re-cloned and checked out at
  exactly these SHAs; `git rev-parse HEAD` confirmed an exact match for each
  before scanning (no upstream drift possible since these are fixed commits,
  not branches).
- **Own.NET commit (current)** — `main` at `4c5a86b` (merge of PR #240, the
  tip of `main` at measurement time — the branch used for this note's own
  doc-only PR is `9d39b8c`, identical analyzer code to `4c5a86b` since Phase 1
  of this cleanup touched no analyzer source).
- **Baseline** — *self-regenerated*, not copied from prose. `OwnSharp.Extractor`
  was also built at Own.NET commit `c029e8d` (`main`, the merge of PR #226 —
  right after `oracle-sweep-2026-07-10.md` landed, before **any** of
  #218-#225's fixes), and run with the identical command against the same
  pinned target commits. This guarantees an apples-to-apples diff across the
  *entire* #218-#240 batch in one pass, rather than stitching together
  partial deltas from three different historical notes that each used
  slightly different repo subsets and Own.NET commits. (Spot check: the
  regenerated baseline's raw SARIF counts exactly match every previously
  published raw-SARIF count where one exists — MahApps.Metro 3, MaterialDesign
  23, AvalonEdit 24, ShareX 235 OWN001 findings match
  `oracle-sweep-rerun-2026-07-11.md`'s "before" column; ClosedXML 270 matches
  `precision-remeasure-2026-07-11.md`'s pre-#233 count. The *hand-triaged*
  "own leak" counts in the original 2026-07-10 table (18, 14, 5) are smaller
  because that table counted post-triage "obvious" sites, not raw SARIF
  results — confirmed by `oracle-sweep-rerun-2026-07-11.md`'s own caveat: "Raw
  finding counts here are literal SARIF result counts, not the hand-grouped
  'own-only' site counts in the 2026-07-10 table".)
- **Command** (identical for baseline and current, both builds):
  ```
  OWN_EXTRA_REF_DIRS=<WindowsDesktop ref pack net8.0> \
    scripts/own-check.sh --format sarif --severity warning -- <target checkout>
  ```
- **Extractor mode** — `--flow-locals` (own-check.sh's default; not
  `--legacy`), matching `oracle-sweep-rerun-2026-07-11.md`'s stated method.
- **Reference resolution** — `microsoft.windowsdesktop.app.ref` 8.0.28,
  `ref/net8.0` (47 DLLs), materialized via a scratch `net8.0-windows`
  `UseWPF`/`UseWindowsForms`/`EnableWindowsTargeting` csproj + `dotnet
  restore`, then exported as `OWN_EXTRA_REF_DIRS` — the exact mechanism
  `ci.yml`'s `corpus-benchmark` job and the established sweep methodology
  both use. OWN050 (unresolved-reference advisory) counts are byte-for-byte
  identical between baseline and current for all 5 targets (confirmed below),
  so reference coverage did not shift — only the fixes' targets did.
- **Diffing** — SARIF results matched by `(ruleId, normalized path, line)`.
  Paths normalized to be relative to each target's repo root (the
  `../targets/<Name>/` prefix `own-check` emits is stripped). Deterministic
  ordering: sorted by `(rule, path, line)`.

## Headline numbers

| target | baseline (pre-#218..#240) | current (post-batch) | Δ | added | removed | OWN050 (unchanged) |
|---|---:|---:|---:|---:|---:|---:|
| ShareX | 350 (235 OWN001 + 115 OWN050) | 314 (199 OWN001 + 115 OWN050) | **−36** | 0 | 36 | 115 = 115 |
| MahApps.Metro | 63 (3 OWN001 + 60 OWN050) | 60 (0 OWN001 + 60 OWN050) | **−3** | 0 | 3 | 60 = 60 |
| MaterialDesignInXamlToolkit | 153 (23 OWN001 + 130 OWN050) | 148 (18 OWN001 + 130 OWN050) | **−5** | 0 | 5 | 130 = 130 |
| AvalonEdit | 29 (23 OWN001 + 1 OWN014 + 5 OWN050) | 22 (17 OWN001 + 0 OWN014 + 5 OWN050) | **−7** | 0 | 7 | 5 = 5 |
| ClosedXML | 270 (270 OWN001) | 270 (270 OWN001) | **0** | 0 | 0 | n/a |
| **total** | **865** | **814** | **−51** | **0** | **51** | |

Zero new findings anywhere (no regressions). Every removed finding is
classified below against a specific merged issue/PR — **0 UNEXPLAINED**.

**ClosedXML is the load-bearing result of this remeasure.** Delta is
identically zero against the *pre-#225* baseline: the #238 soundness
regression (263 findings silently swallowed by the source-empty-Dispose
exemption trusting `XLWorkbook.Dispose()` despite `Janitor.Fody` weaving real
cleanup into it) is fully closed by #240's `IEnumerator<T>`-only narrowing —
confirmed here independently of #240's own PR-description remeasure (which
used a narrower `--flow-locals`-only, loose-file-resolution setup against a
newer HEAD, by its own admission not a full `own-check` sweep). This run used
the full `own-check.sh --format sarif` sweep against the exact pinned commit
and got the same qualitative answer: **nothing silently disappeared.**

## Classification of every removed finding

### ShareX (36 removed)

| shape | issue / PR | count | example |
|---|---|---:|---|
| WinForms `Controls.Add`/`IContainer` disposal channel | #219 / PR #236 | 29 | `Forms/ImageViewer.cs:396-399`, `Forms/TrayForm.cs:33` |
| `using (field = new T())` release | #220 / PR #231 | 3 | `Cryptographic/HashChecker.cs:42`, `TaskEx.cs:41`, `IndexerLib/IndexerJson.cs:35` |
| self-populated owned-collection element | #229 / PR #239 | 4 | `Shapes/ShapeManager.cs:369-382` (`DrawableObjects` — populated by `ShapeManager` itself, then iterated with `+=` in the same ctor) |

### MahApps.Metro (3 removed)

| shape | issue / PR | count | example |
|---|---|---:|---|
| DP/property-changed old→new subscription rotation | #218 / PR #230 | 1 | `Actions/CommandTriggerAction.cs:116` |
| `Behavior.AssociatedObject` self-owned source | #227 / PR #237 | 1 | `Behaviors/TiltBehavior.cs:70` |
| template-part local (`GetTemplateChild` pattern-var) | #222 / PR #231 | 1 | `Controls/MetroWindow.cs:1448` |

### MaterialDesignInXamlToolkit (5 removed)

| shape | issue / PR | count | example |
|---|---|---:|---|
| curated app-scoped source (`PaletteHelper.GetThemeManager`) | #228 / PR #232 | 1 | `MahMaterialDragablzMashUp/App.xaml.cs:22` |
| DP/property-changed old→new subscription rotation | #218 / PR #230 | 4 | `MaterialDesignThemes.Wpf/SmartHint.cs:205-208` |

### AvalonEdit (7 removed)

| shape | issue / PR | count | example |
|---|---|---:|---|
| template-part local (`FindName` pattern-var) | #222 / PR #231 | 2 | `CodeCompletion/OverloadViewer.cs:58,64` |
| DP/property-changed old→new subscription rotation | #218 / PR #230 | 3 | `Editing/AbstractMargin.cs:99`, `Editing/LineNumberMargin.cs:114`, `Folding/FoldingMargin.cs:218` |
| self-detaching handler | #224 / PR #231 | 1 | `Search/DropDownButton.cs:78` |
| `CommandManager.RequerySuggested` weak-event allowlist | #223 / PR #231 | 1 | `Editing/ImeSupport.cs:47` (OWN014) |

### ClosedXML (0 removed)

Nothing removed. See "load-bearing result" above.

Every classification above was verified by reading the actual current source
at the cited location (not inferred from the shape's name) — e.g. confirming
`ShapeManager.cs`'s `DrawableObjects` is populated only by
`DrawableObjects = new List<ImageEditorControl>()` / `.Add(node)` inside
`ShapeManager` itself before the `foreach` that subscribes, and that
`HashChecker.cs`'s `cts` field is the direct target of `using (cts = new
CancellationTokenSource())`.

## Previously confirmed true positives — preserved

Spot-checked directly against the current SARIF (not assumed from the
"removed" list being empty at these sites):

- ShareX flagship: `ShareX.ScreenCaptureLib/Shapes/ShapeManagerMenu.cs:47`
  (`menuForm`, the corpus-reduced flagship leak) — **present**. The
  `HistoryItemManager`/`HistoryItemManager_ContextMenu.cs` cluster (~50
  `ToolStripMenuItem`/`ToolStripSeparator` fields) — **present**, all of them.
- AvalonEdit: `Rendering/TextView.cs:1843` (`services`), `:1946`
  (`hoverLogic`) — **present**, both.
- ClosedXML: `ClosedXML.Tests/Excel/CalcEngine/FunctionsTests.cs:285` (`cts`,
  genuine undisposed `CancellationTokenSource`), `ClosedXML.Tests/Excel/Ranges/
  UsedAndUnusedCellsTests.cs:10` (`workbook` field) — **present**, both.

No previously confirmed true positive disappeared in this remeasure.

## Stop-condition checklist

- Confirmed true positive disappearing? **No** — all spot-checked above.
- Command/corpus differs from baseline? **No** — identical `own-check.sh`
  invocation, identical `OWN_EXTRA_REF_DIRS` setup, identical pinned target
  commits for both the baseline and current runs (verified by `git
  rev-parse`).
- Delta contradicts a merged PR claim? **No** — every removed finding maps
  to the exact shape its issue/PR describes; ClosedXML's zero delta matches
  #240's own "0 removed" claim, independently reproduced here.
- ClosedXML findings disappearing under the empty-Dispose exemption despite
  Fody being active? **No** — zero ClosedXML findings disappeared; the #240
  gate (confined to `IEnumerator<T>` implementers, with a `FodyWeavers.xml`
  kill-switch) does not touch ClosedXML's `XLWorkbook`/`Slice.Enumerator`
  shapes here.
- Unrecorded local environment assumption? The WindowsDesktop ref pack
  version (8.0.28) is recorded above and in the machine-readable data;
  `dotnet --version` was `8.0.422` for both builds (same installed SDK, one
  install, two `dotnet build` invocations against different Own.NET
  checkouts).

None of the stop conditions triggered.

## Machine-readable data

Per-target JSON (schema: `target`, `target_commit`, `ownnet_commit`,
`ownnet_baseline_commit`, `command`, `extractor_mode`,
`reference_resolution`, `baseline_source`, `counts`, `added`, `removed`
(each entry carries `explained_by_issue`/`explained_by_pr`/`shape`, or
`"UNEXPLAINED"`), `changed`) in
[`precision-remeasure-2026-07-12-data/`](precision-remeasure-2026-07-12-data/):
`ShareX.json`, `MahApps.Metro.json`, `MaterialDesignInXamlToolkit.json`,
`AvalonEdit.json`, `ClosedXML.json`. Counts and classifications in this prose
note were generated from the same diff run that produced these files (no
independent transcription) — this is the meaning of "prose and
machine-readable agree" for this note.

## Scope note

No analyzer code was changed to produce this note. This is a measurement-only
PR, per the guardrail that analyzer changes and measurement must not be mixed
in the same PR.
