# Precision re-measure — 2026-07-11 (verifying #218/#220/#222/#223/#224 and #225/#228)

Follow-up to [`oracle-sweep-2026-07-10.md`](oracle-sweep-2026-07-10.md) (issue \#201),
which drafted 8 precision-gap issues from real own-only findings in 5
OSS repos: #218-#225. Four follow-up PRs have since shipped fixes:

- [#230](https://github.com/PhysShell/Own.NET/pull/230) — Closes **#218**
  (not #219 — #219 is the separate WinForms `Controls`/`IContainer` disposal
  channel gap, still open **as of this note**; shipped later via PR #236,
  see `docs/notes/field-notes-patterns.md` entry 12/13). DependencyProperty/
  property-changed old→new subscription-rotation recognition.
- [#231](https://github.com/PhysShell/Own.NET/pull/231) — four smaller gaps
  in one PR: `CommandManager.RequerySuggested` allowlist (#223),
  `using (field = new T())` release (#220), template-part local/pattern-var
  exemption (#222), self-detaching handler (#224).
- [#232](https://github.com/PhysShell/Own.NET/pull/232) — Closes **#228**
  (sub-part (b) of the parent #221 split), curated app-scoped source
  exemption for an `Application`-derived subscriber.
- [#233](https://github.com/PhysShell/Own.NET/pull/233) — Closes **#225**,
  exempt locals of user types whose `Dispose()` is provably empty in source.

This note has two parts: **Part 1** formalizes yesterday's measurement of
\#230/\#231 against the 2026-07-10 baseline (same method as before, now with
the #218/#219 numbering corrected). **Part 2** reruns the same method against
today's fresh `main` (with #232/#233 also merged) for the two repos those
fixes target, and checks the actual delta against the expected delta each
PR's own "validation plan" section predicted.

## Method (unchanged from the 2026-07-10 rerun)

- Same repo clones, same pinned commits as the original sweep: MahApps.Metro
  `72099e3`, MaterialDesignInXamlToolkit `ef3a5ea`, AvalonEdit `ed0bd14`,
  ShareX `0df9ca4`, ClosedXML `4e89dce` — no drift from upstream, an
  apples-to-apples comparison.
- `OwnSharp.Extractor` built fresh off the `main` commit under test.
- `scripts/own-check.sh --format sarif --severity warning -- <repo>`, same
  `OWN_EXTRA_REF_DIRS` (WindowsDesktop ref pack) as `oracle.yml` uses.
- SARIF results diffed by normalized `(file, line)` per rule ID between the
  "before" and "after" runs.

## Part 1 — #218/#220/#222/#223/#224 delta (`main` at `3ca4bde`, #230+#231 merged)

| repo | OWN001+OWN014 before | after | Δ | new findings introduced |
|---|---:|---:|---:|---:|
| MahApps.Metro | 3 | 1 | **−2** | 0 |
| MaterialDesignInXamlToolkit | 23 | 19 | **−4** | 0 |
| AvalonEdit | 24 (23 OWN001 + 1 OWN014) | 17 | **−7** | 0 |
| ShareX | 235 | 232 | **−3** | 0 |
| **total** | **285** | **269** | **−16** | **0** |

Zero new findings anywhere. OWN050 (unresolved-reference advisory) counts are
byte-for-byte identical before/after in all 4 repos — coverage didn't shift,
only the fixes' targets did.

### Removed findings, mapped to the fix that closed them

| repo | site | issue / PR | rule |
|---|---|---|---|
| MahApps.Metro | `Actions/CommandTriggerAction.cs:116` | **#218** / #230 (DP rotation) | OWN001 |
| MahApps.Metro | `Controls/MetroWindow.cs:1448` | #222 / #231 (template-part pattern var) | OWN001 |
| MaterialDesignInXamlToolkit | `SmartHint.cs:205-208` (×4) | **#218** / #230 (DP rotation) | OWN001 |
| AvalonEdit | `Editing/AbstractMargin.cs:99` | **#218** / #230 (DP rotation) | OWN001 |
| AvalonEdit | `Editing/LineNumberMargin.cs:114` | **#218** / #230 (DP rotation) | OWN001 |
| AvalonEdit | `Folding/FoldingMargin.cs:218` | **#218** / #230 (DP rotation) | OWN001 |
| AvalonEdit | `CodeCompletion/OverloadViewer.cs:58,64` | #222 / #231 (template-part local) | OWN001 |
| AvalonEdit | `Search/DropDownButton.cs:78` | #224 / #231 (self-detaching handler) | OWN001 |
| AvalonEdit | `Editing/ImeSupport.cs:47` (`CommandManager.RequerySuggested`) | #223 / #231 (weak-event allowlist) | **OWN014** |
| ShareX | `Cryptographic/HashChecker.cs:42` | #220 / #231 (`using (field = new T())`) | OWN001 |
| ShareX | `TaskEx.cs:41` | #220 / #231 | OWN001 |
| ShareX | `IndexerJson.cs:35` | #220 / #231 | OWN001 |

By fix: rotation (**#218**/#230) accounts for 8 of the 16 removed findings —
beating the "−6+" estimate from the original sweep note (which only
individually verified 6 sites; the rerun confirms all 8 rotation sites in
the baseline actually clear). The other three #231 fixes account for the
remaining 8: template-part locals (3), self-detach (1), weak-event allowlist
(1, on the OWN014 hard-error tier as designed), using-field release (3).

### Real bugs — confirmed still flagged

ShareX `HistoryLib/HistoryItemManager_ContextMenu.cs` cluster (48 findings —
no `Dispose()` at all), ShareX `ShapeManagerMenu.cs` cluster (the flagship
`menuForm` leak), ShareX plain `Timer`/`ImageList` fields
(`ColorUserControl.cs`, `AutoCaptureForm.cs`, `UploadersConfigForm.cs`), and
AvalonEdit `TextView.cs:1843,1946` — all unchanged, still flagged.

### Still open (out of #230/#231's scope)

MahApps.Metro `Behaviors/TiltBehavior.cs:70` (self-owned `Behavior<T>`
source, #227) and MaterialDesignInXamlToolkit's remaining 19 findings —
`App.xaml.cs:22`, `ListsAndGridsViewModel.cs` (#229), `CircleWipe.cs`/
`FadeWipe.cs`, the 7 bulk-review `themeManager.ThemeChanged` sites, etc. —
untouched, as expected.

## Expected delta of the next measurement (before rerunning)

Predicted from #232's and #233's own PR bodies, before this note's Part 2
below actually reran anything:

- **After #232 (Closes #228):** MaterialDesignInXamlToolkit
  `MahMaterialDragablzMashUp/App.xaml.cs:10,22` (`themeManager.ThemeChanged`
  on the `App`-derived subscriber) should drop out of own-only.
- **After #233 (Closes #225):** ClosedXML `Excel/Cells/Slice.cs:91,109,149,188,219`
  — five `Slice.Enumerator`/`ReverseEnumerator` locals, all sharing the
  same empty-`Dispose()` root — should drop out of own-only.
- **Not yet fixed (#227, #229 — still open):** MahApps.Metro
  `Behaviors/TiltBehavior.cs:70` and MaterialDesignInXamlToolkit
  `ListsAndGridsViewModel.cs:16-17` (both demo variants) should remain
  flagged.

## Part 2 — actual #232/#233 delta (`main` at `b1ee961`, #232+#233 also merged)

| repo | before (after #230/#231) | after (+ #232/#233) | Δ | expected Δ |
|---|---:|---:|---:|---:|
| MaterialDesignInXamlToolkit | 19 | 18 | **−1** | −1 (1 site) |
| ClosedXML | 270 | 5 | **−265** | −5 (1 site's 5 locals) |

### MaterialDesignInXamlToolkit — matches expectation

`MahMaterialDragablzMashUp/App.xaml.cs:22` (the only SARIF-reportable line
for that site — line 10 in the issue's citation is the `PaletteHelper()`
resolver-call context line, not a second finding) dropped out, exactly as
predicted. No other site moved. **Match.**

### ClosedXML — does NOT match expectation, and not in the way "more FPs cleared than expected" sounds

The raw delta (−265) looks like a huge overachievement of the predicted −5,
but breaking it down site-by-site shows it is **not** a clean superset —
part of it is a real coverage gap, and the bulk of it is a genuine, unsound
over-exemption that needs its own follow-up issue. Do not read "−265" as
"the fix worked great"; read the breakdown below.

**1) Only 2 of the 5 predicted Slice.cs sites actually cleared:**

| line | local | enumerator type | `Dispose()` form | cleared? |
|---:|---|---|---|:---:|
| 91 | `enumerator` | `Enumerator` | `void IDisposable.Dispose() { }` — **explicit interface implementation** | ❌ still flagged |
| 109 | `cellEnumerator` | `Enumerator` | same explicit-interface form | ❌ still flagged |
| 149 | `cellEnumerator` | `Enumerator` | same explicit-interface form | ❌ still flagged |
| 188 | `cellEnumerator` | `ReverseEnumerator` | `public void Dispose() { }` — plain method | ✅ cleared |
| 219 | `enumerator` | `ReverseEnumerator` | same plain-method form | ✅ cleared |

`HasEmptyDisposeBody` (the check #233 shipped) recognizes a plain
`public void Dispose() { }` declaration but not an explicit interface
implementation (`void IDisposable.Dispose() { }`) — same empty body,
different declaration syntax. This is a **coverage gap** (the check is
too narrow, not unsound): `Enumerator` and `ReverseEnumerator` sit right
next to each other in the same file with the identical empty body, and
only one form is recognized.

**2) The other 263 removed findings are an unrelated, unsound over-exemption:**
every one of them is a `wb`/`workbook`/`wb1`/`wb2`/`wb_saved`/`wbSource`
local of type `XLWorkbook`, scattered across `ClosedXML.Examples` (263
call sites in total) — nothing to do with `Slice.cs` at all. The root
cause: `ClosedXML/Excel/XLWorkbook.cs:874`

```csharp
public void Dispose()
{
    // Leave this empty so that Janitor.Fody can do its work
}
```

is empty **in source only**. `Janitor.Fody` is a build-time IL weaver that
rewrites this exact method body at compile time to call the adjacent
`DisposeManaged()` (`XLWorkbook.cs:868`, which does real cleanup —
`Worksheets.ForEach(w => (w as XLWorksheet).Cleanup())`). A Roslyn-source
analyzer has no visibility into post-compile IL weaving, so
`HasEmptyDisposeBody`'s "zero-statement block ⇒ no-op" heuristic reads the
comment-explained placeholder as a genuine no-op and exempts every
`XLWorkbook` local in the compilation — even though disposing one
(pre-weaving semantics aside) is exactly what real ClosedXML code is
supposed to do, and never calling it is a real, if fairly benign
(process-exit-scoped example code), leak.

This is **not** what #233 set out to do (#233's own PR body scoped the fix
to "only locals," and its acceptance checklist's regression diff was run
against the existing sample corpus, which has no Fody-woven-Dispose type in
it — so this shape never showed up in that PR's own local verification).
It's a real precision regression surfaced only by running against actual
OSS code that uses a code-weaving library, exactly the kind of gap a
synthetic-sample-only regression suite can't catch.

**Confirmed unaffected (real findings, unrelated to this fix):**
`ClosedXML.Tests/Excel/CalcEngine/FunctionsTests.cs:285` (`cts`, a genuine
undisposed `CancellationTokenSource`) and
`ClosedXML.Tests/Excel/Ranges/UsedAndUnusedCellsTests.cs:10` (`workbook`
field, real) — both still flagged, so the over-exemption is scoped to
`XLWorkbook` **locals** specifically (matches #233's own "only locals, not
fields" boundary), not a wholesale collapse of ClosedXML's findings.

### Net read for the next iteration (analyzer code NOT touched in this note)

Two separate, differently-shaped follow-ups for whoever picks this up next:

1. **Coverage gap** — extend `HasEmptyDisposeBody` to also recognize an
   empty **explicit interface implementation** `Dispose()`
   (`void IDisposable.Dispose() { }`), not just a plain public method
   declaration. Closes the remaining 3/5 Slice.cs sites (91, 109, 149).
2. **Soundness regression** — `HasEmptyDisposeBody` needs to stop treating
   a literally-empty `Dispose()` as proof of "nothing
   to release" when IL-weaving tools (Janitor.Fody being the concrete
   instance found here; PostSharp and other Fody plugins follow the same
   shape) are in play. A cheap, conservative signal: if the type or any
   partial-class fragment also declares a private method whose body the
   weaver targets by convention (Janitor.Fody's own convention is a method
   named `Dispose(Managed|Unmanaged)`/`DisposeManaged`/`DisposeUnmanaged`
   living alongside the empty `Dispose()`), don't exempt — treat it as
   "provably non-empty at runtime" and fall back to today's flagged
   behavior. Whether that specific heuristic is the right one is a design
   call for whoever picks up the fix, not decided here.

This note's own instructions were read-only with respect to the analyzer —
no code was changed to investigate or produce the breakdown above; the
breakdown is entirely from comparing old/new SARIF output and reading the
target repos' real source.

## Resolution addendum (2026-07-11 / 2026-07-12)

Both follow-ups identified above were filed and shipped as a single unit:
issue [#238](https://github.com/PhysShell/Own.NET/issues/238) (soundness
regression — item 2 above, the ClosedXML 263-finding over-exemption) with
the explicit-interface coverage gap (item 1 above) folded into the same
fix, closed by [PR #240](https://github.com/PhysShell/Own.NET/pull/240).
The shipped fix took the narrowing direction (confine the exemption to
types implementing the generic `System.Collections.Generic.IEnumerator<T>`,
not the non-generic `IEnumerator`) rather than the weaver-convention-sniffing
heuristic sketched in item 2 — see
`docs/notes/field-notes-patterns.md` entry 19 for the full account,
including why the original "−5 Slice.cs points, 263 restored" acceptance
target from #238 was itself corrected (ClosedXML's own `FodyWeavers.xml`
covers `Slice.cs` too, so the sound outcome is "fully restored, nothing
silently dropped," not a fixed `−5`).
