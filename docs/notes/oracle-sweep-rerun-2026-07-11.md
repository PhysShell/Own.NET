# Oracle sweep rerun — 2026-07-11 (verifying #230/#231 against the 2026-07-10 baseline)

Follow-up to [`oracle-sweep-2026-07-10.md`](oracle-sweep-2026-07-10.md) (issue
#201). That sweep drafted 8 precision-gap issues (#218-#225) from real
own-only findings in 5 OSS repos. Two follow-up PRs have since shipped fixes:

- [#230](https://github.com/PhysShell/Own.NET/pull/230) — DependencyProperty/
  property-changed old→new subscription-rotation recognition (issue #219).
- [#231](https://github.com/PhysShell/Own.NET/pull/231) — four smaller
  precision gaps in one PR: `CommandManager.RequerySuggested` allowlist
  (#223), `using (field = new T())` release (#220), template-part
  local/pattern-var exemption (#222), self-detaching handler (#224).

This note reruns `own-check` (the real Roslyn extractor + Python core, not
the CodeQL/Infer# cross-tool oracle — that side of the comparison is
unaffected by these fixes) against the **same 4 repos, at the exact same
pinned commits** as the 2026-07-10 sweep, on `main` at `3ca4bde` (both PRs
merged), and diffs the resulting SARIF against the `own.txt` baselines kept
from that sweep. Goal: confirm the fixes silence exactly the documented false
positives, add no regressions, and leave every documented real bug flagged.

## Method

- Reused the exact repo clones from the 2026-07-10 run (still pinned at the
  same commits: MahApps.Metro `72099e3`, MaterialDesignInXamlToolkit
  `ef3a5ea`, AvalonEdit `ed0bd14`, ShareX `0df9ca4`) — an apples-to-apples
  comparison, no drift from upstream changes.
- Built `OwnSharp.Extractor` fresh off `origin/main` (`3ca4bde`).
- Ran the identical command the `oracle.yml` workflow uses:
  `scripts/own-check.sh --format sarif --severity warning -- <repo>`, with
  the same `OWN_EXTRA_REF_DIRS` (WindowsDesktop ref pack) materialized the
  same way, so framework-event resolution is on equal footing with the
  original run (confirmed: OWN050 unresolved-reference advisory counts are
  byte-for-byte identical before/after in all 4 repos — coverage didn't
  shift, only the fixes' targets did).
- Diffed old vs new SARIF results by normalized `(file, line)` per rule ID.

## Headline delta

| repo | OWN001+OWN014 before | after | Δ | new findings introduced |
|---|---:|---:|---:|---:|
| MahApps.Metro | 3 | 1 | **−2** | 0 |
| MaterialDesignInXamlToolkit | 23 | 19 | **−4** | 0 |
| AvalonEdit | 24 (23 OWN001 + 1 OWN014) | 17 | **−7** | 0 |
| ShareX | 235 | 232 | **−3** | 0 |
| **total** | **285** | **269** | **−16** | **0** |

Zero new findings anywhere — the fixes are pure precision gains, not
trade-offs. (Raw finding counts here are literal SARIF result counts, not
the hand-grouped "own-only" site counts in the 2026-07-10 table, so absolute
numbers differ slightly from that table; deltas are what matter.)

## Removed findings, mapped to the fix that closed them

| repo | site | issue / PR | rule |
|---|---|---|---|
| MahApps.Metro | `Actions/CommandTriggerAction.cs:116` | #219 / #230 (DP rotation) | OWN001 |
| MahApps.Metro | `Controls/MetroWindow.cs:1448` | #222 / #231 (template-part pattern var) | OWN001 |
| MaterialDesignInXamlToolkit | `SmartHint.cs:205-208` (×4) | #219 / #230 (DP rotation) | OWN001 |
| AvalonEdit | `Editing/AbstractMargin.cs:99` | #219 / #230 (DP rotation) | OWN001 |
| AvalonEdit | `Editing/LineNumberMargin.cs:114` | #219 / #230 (DP rotation) | OWN001 |
| AvalonEdit | `Folding/FoldingMargin.cs:218` | #219 / #230 (DP rotation) | OWN001 |
| AvalonEdit | `CodeCompletion/OverloadViewer.cs:58,64` | #222 / #231 (template-part local) | OWN001 |
| AvalonEdit | `Search/DropDownButton.cs:78` | #224 / #231 (self-detaching handler) | OWN001 |
| AvalonEdit | `Editing/ImeSupport.cs:47` (`CommandManager.RequerySuggested`) | #223 / #231 (weak-event allowlist) | **OWN014** |
| ShareX | `Cryptographic/HashChecker.cs:42` | #220 / #231 (`using (field = new T())`) | OWN001 |
| ShareX | `TaskEx.cs:41` | #220 / #231 | OWN001 |
| ShareX | `IndexerJson.cs:35` | #220 / #231 | OWN001 |

By fix: rotation (#219/#230) accounts for 8 of the 16 removed findings —
beating the "−6+" estimate from the original sweep note (which only
individually verified 6 sites; the rerun confirms all 8 rotation sites in
the baseline actually clear). The other three #231 fixes account for the
remaining 8: template-part locals (3), self-detach (1), weak-event allowlist
(1, on the OWN014 hard-error tier as designed — not OWN001), using-field
release (3).

## Real bugs — confirmed still flagged

Every documented true positive from the 2026-07-10 triage is still present,
unchanged, after the rerun:

- ShareX `HistoryLib/HistoryItemManager_ContextMenu.cs` cluster (48 findings
  — no `Dispose()` at all).
- ShareX `ShapeManagerMenu.cs` cluster (the flagship `menuForm` leak,
  reduced to `corpus/real-world/sharex-shapemanager-menuform-leak/`).
- ShareX plain `Timer`/`ImageList` fields (`ColorUserControl.cs`,
  `AutoCaptureForm.cs`, `UploadersConfigForm.cs`).
- AvalonEdit `TextView.cs:1843,1946` (`services`, `hoverLogic` — no
  `Dispose()` at all).

## Still open (out of this fix pair's scope)

Findings tied to issue #221 (self-owned-source exemption too narrow —
`Behavior<T>.AssociatedObject`, app-scoped subscriber, self-owned-collection-
element) are untouched, as expected — #221 wasn't part of #230/#231:

- MahApps.Metro `Behaviors/TiltBehavior.cs:70` (the sole remaining finding).
- MaterialDesignInXamlToolkit `App.xaml.cs:22`, `ListsAndGridsViewModel.cs`,
  `CircleWipe.cs`/`FadeWipe.cs`, and the 7 bulk-review
  `themeManager.ThemeChanged` sites (19 remaining findings total).

## Not rerun

ClosedXML (the clean-code control from the original sweep) wasn't included —
none of its findings related to #219-#225, and it isn't part of the WPF/
WinForms domain #230/#231 targeted. The CodeQL/Infer# oracle side wasn't
rerun either — these fixes only change Own.NET's own emission, and the
oracle comparators' output is unaffected by them.
