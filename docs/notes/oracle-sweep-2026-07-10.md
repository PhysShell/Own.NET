# Oracle sweep — 2026-07-10 (issue #201)

Per `docs/notes/consolidation-and-positioning.md` ("the actual priority" is
proving value), this run points the cross-tool oracle
([`oracle.md`](oracle.md)) at **5 new** OSS C# repos never mined before —
WPF/WinForms UI toolkits and apps (the domain the flagship ScreenToGif find
came from) plus a plain, no-UI library as the clean-code control.

**Triage boundary (read before the table).** Draft verdicts below are only for
**obvious** cases, each verified against the target's real cloned source (not
guessed from the SARIF message alone). Anything ambiguous — where the ownership
chain wasn't fully traced, or a custom type's semantics weren't read — is called
out explicitly as **needs maintainer review**, not silently resolved. These are
still *drafts*: final TP/FP dispositions (and anything that feeds
`corpus/oracle-fp-baseline.txt`) are the maintainer's call. No analyzer code was
touched in this PR — every precision gap found is filed as its own follow-up
issue instead (linked at the end).

## How this ran

`workflow_dispatch` on `oracle.yml` isn't available to this session's token
(`403 Resource not accessible by integration` — the same limitation
`real-world-mining.md` already records for `mine.yml`). Reused the documented
push-triggered dev-loop fallback instead: `oracle.yml`'s `push` path +
`corpus/oracle-target.txt`, temporarily pointed at this PR's branch. Both are
reverted to their pre-sweep state before merge (dev-loop scaffolding only, per
the existing convention in `real-world-mining.md`).

## Targets and headline numbers

| repo | domain | commit | Own.NET leak | oracle leak | agree | own-only | oracle-only |
|---|---|---|---:|---:|---:|---:|---:|
| [ShareX/ShareX](https://github.com/ShareX/ShareX) | WinForms app (screen capture — same domain as the ScreenToGif flagship) | `0df9ca4` | 235 | 70 (CodeQL; Infer# skipped — no unique buildable project) | 5 | 230 | 65 |
| [MahApps/MahApps.Metro](https://github.com/MahApps/MahApps.Metro) | WPF UI toolkit | `72099e3` | 3 | 0 (CodeQL) | 0 | 3 | 0 |
| [MaterialDesignInXAML/MaterialDesignInXamlToolkit](https://github.com/MaterialDesignInXAML/MaterialDesignInXamlToolkit) | WPF UI toolkit + demo apps | `ef3a5ea` | 18 | 4 (CodeQL) | 0 | 18 | 4 |
| [icsharpcode/AvalonEdit](https://github.com/icsharpcode/AvalonEdit) | WPF text-editor control | (run HEAD) | 14 | 8 (CodeQL) | 0 | 14 | 8 |
| [ClosedXML/ClosedXML](https://github.com/ClosedXML/ClosedXML) | plain library (Excel/OOXML, no UI) — clean-code control | (run HEAD) | 5 | 8 (Infer#) | 0 | 5 | 8 |

`Agree = 0` on 4 of 5 repos (only ShareX has 5) for the reason `oracle.md`
already documents: Own.NET's niche (subscription/lifetime, field-disposal) and
the oracles' niche (local-not-disposed/RAII) are largely orthogonal on
UI-heavy code — this run doesn't change that picture, it widens the sample.

**Honest coverage accounting** (OWN050 "unresolved external type" markers in
each repo's raw SARIF, `own.txt`, out of all rule references):

| repo | OWN050 | total rule refs | note |
|---|---:|---:|---|
| ShareX | 115 | 350 | GDI+/WinForms-heavy; the WindowsDesktop ref pack resolves most, GDI+ (`System.Drawing`) types partially |
| MahApps.Metro | 60 | 63 | almost entirely unresolved — MahApps leans on `ControlzEx` (a NuGet dependency own-check can't restore without a build), so most of its own event/type surface is invisible to the extractor |
| MaterialDesignInXamlToolkit | 130 | 153 | same shape — also depends on `ControlzEx`/`MaterialDesign3`-adjacent packages |
| AvalonEdit | 5 | 29 | mostly self-contained WPF, few externals |
| ClosedXML | 0 | 270 | plain library, all first-party/BCL |

MahApps and MaterialDesignInXamlToolkit's own-only counts should be read against
that backdrop: **most of each codebase wasn't actually analysable** (unresolved
external types dominate), so their small `own-only` counts are partly "there
wasn't much left to check," not purely "the tool looked hard and found little."
This mirrors the exact caveat `oracle.md`'s Dapper worked example already
flags — a clean/small result can mean "correctly clean" or "didn't reach it,"
and only the OWN050 ratio tells them apart.

## Findings table (draft verdicts)

Legend: **FP** = draft false positive (verified against source); **TP** = draft
true positive (real, if sometimes low-severity); **review** = needs maintainer
review (ambiguous or not independently traced).

| repo | finding (code, location) | draft verdict | rationale (cross-tool coverage: oracle stayed silent on all of these — no oracle has an event-subscription-leak query, and none of the disposal-channel/no-op-dispose gaps below are things CodeQL/Infer#'s `local-not-disposed` model either) |
|---|---|---|---|
| ShareX | OWN001, ~24 sites (`ColorPicker.cs:84-85`, `ImageViewer.cs:396-399`, `InputBox.cs:145-147`, …) | **FP** | WinForms child-`Control` field added via `Controls.Add`/`AddRange`; `base.Dispose(disposing)` disposes the `Controls` collection transitively (verified: `Controls.Add(this.txtSelectedClipboardContent)` etc. in the same file, in each spot-checked case) |
| ShareX | OWN001, ~6 sites (`TrayForm.cs:33` `TrayIcon`, …) | **FP** | constructed `new T(components)` / registered `components.Add(x)` — the designer's `IContainer components.Dispose()` disposes it |
| ShareX | OWN001, `HashChecker.cs:42` `cts`, `TaskEx.cs:41` `cts`, `IndexerJson.cs:35` `jsonWriter` | **FP** | `using (field = new T())` — the field *is* the `using` acquisition target, disposed at scope exit; the flow detector doesn't recognise a field (vs. a local) in that position |
| ShareX | OWN001, `HistoryItemManager_ContextMenu.cs` cluster (48 findings: `cmsHistory` + ~47 child `ToolStripMenuItem`/`Separator` fields) | **TP** | `HistoryItemManager` has **no `Dispose` method at all** (grepped both partial-class files) — real, if low-severity, leak |
| ShareX | OWN001, `ShapeManagerMenu.cs` cluster (39 findings: `menuForm` + ~38 ToolStrip child fields) — **flagship** | **TP** | `ShapeManager.Dispose()` (`ShapeManager.cs:2406`) disposes `history` but never `menuForm`; every capture/annotation session leaks a full `Form` + toolbar. Reduced to `corpus/real-world/sharex-shapemanager-menuform-leak/` |
| ShareX | OWN001, `ColorUserControl.cs:93` `mouseMoveTimer`, `AutoCaptureForm.cs:57-58` `statusTimer`/`screenshotTimer`, `UploadersConfigForm.cs:47` `uploadersImageList` | **TP** | plain `new Timer()`/`new ImageList()`, not container-registered, never disposed |
| ShareX | OWN001, `ColorPickerForm.cs:44` `clipboardStatusHider`, `AboutForm.cs:36` `easterEgg`, `MainForm.cs:49` `actionsMenuIconCache` | **review** | never disposed, but the custom types' own Dispose semantics weren't read |
| ShareX | OWN001, 89 event-subscription findings (`event 'X.Y' is subscribed … injected dependency`) | **review, bulk** | not individually verified; one spot-check (`ToolStripRadioButtonMenuItem.cs:233`, subscribing to `OwnerItem`, its own parent in the menu tree) suggests a co-lifetime shape similar to an already-shipped exemption, but not confirmed for the other 88 |
| MahApps.Metro | OWN001, `Actions/CommandTriggerAction.cs:116` | **FP** | `OnCommandChanged` unsubscribes the *old* command's `CanExecuteChanged` and subscribes the *new* one, same handler — a DependencyProperty subscription-rotation idiom, not an unbounded leak |
| MahApps.Metro | OWN001, `Behaviors/TiltBehavior.cs:70` | **FP** | subscribes `panel.Loaded` where `panel == this.AssociatedObject` — the Behavior's own attached element; co-lifetimed by construction (`Behavior<T>`) |
| MahApps.Metro | OWN001, `Controls/MetroWindow.cs:1448` | **FP** | `GetTemplateChild(...) is MetroContentControl metroContentControl` — a template part captured as a **local pattern variable**, same safe shape as the already-shipped field-based self-owned-template-part exemption, narrower syntactic form |
| MaterialDesignInXamlToolkit | OWN001, `App.xaml.cs:22` (`themeManager.ThemeChanged`) | **FP** | subscriber is `App : Application`; source is `PaletteHelper().GetThemeManager()` → an app-scoped `IThemeManager` bound to the app's own `ResourceDictionary` — co-lifetimed with the `Application` singleton, just not a literal `static` field |
| MaterialDesignInXamlToolkit | OWN001, 7× `themeManager.ThemeChanged` in `MainWindow.xaml.cs`/ViewModels (2 demo apps) | **review, bulk** | same source, but the subscriber is a plain window/ViewModel, not provably process-lived — Own.NET's advisory warning is arguably the honest answer, not confirmed as a bug |
| MaterialDesignInXamlToolkit | OWN001, `SmartHint.cs:205-208` (4 findings) | **FP** | second confirmed instance of the DP old→new subscription-rotation shape (see MahApps) |
| MaterialDesignInXamlToolkit | OWN001, `CircleWipe.cs:75`, `FadeWipe.cs:59` | **FP** | subscribe on a freshly-constructed, returned `Timeline` — matches the already-catalogued "returned-fresh publisher" idiom (`field-notes-patterns.md` entry 8); this specific single-method construct-subscribe-return shape isn't confirmed covered by the shipped fix — **worth a maintainer check**, not asserted as a fresh gap |
| MaterialDesignInXamlToolkit | OWN001, `ListsAndGridsViewModel.cs:16-17` (both demo variants) | **FP** | subscribing to `+=` on an element of `Items1`, a collection the ViewModel constructs itself in its own ctor — self-owned-collection-element, a new variant of the shipped self-owned-source idea |
| AvalonEdit | OWN001, `AbstractMargin.cs:99`, `LineNumberMargin.cs:114`, `FoldingMargin.cs:218` | **FP** | third confirmed repo for the DP/property-changed old→new subscription-rotation shape — here as a plain virtual `OnTextViewChanged(old, new)` override, not just a `PropertyChangedCallback` |
| AvalonEdit | OWN001, `OverloadViewer.cs:58,64` | **FP** | second confirmed instance of "template part via `FindName`, stored as a local" (see MahApps `MetroWindow`) |
| AvalonEdit | OWN001, `ImeSupport.cs:47` (`CommandManager.RequerySuggested`) | **FP** | the in-repo comment confirms this WPF/BCL event is implemented over **weak references** specifically to avoid the "static event pins subscriber" trap — Own.NET's static-source hard-error is the wrong tier for this one named event |
| AvalonEdit | OWN001, `DropDownButton.cs:78` | **FP** | the handler's own body (`DropDownContent_Closed`) calls `-=` against itself on first firing — a self-detaching handler, never flagged as bounded |
| AvalonEdit | OWN001, `Caret.cs:51-52`, `TextAreaAutomationPeer.cs:35-36`, `ImeSupport.cs:48` | **review** | plausible composition-owned back-references (Caret/AutomationPeer/ImeSupport are each constructed by the very `TextArea`/`TextView` whose event they subscribe to), but the owning class's construction wasn't traced far enough to confirm |
| AvalonEdit | OWN001, `TextView.cs:1843` `services`, `:1946` `hoverLogic` | **TP** | `TextView` has no `Dispose` method at all (grepped the whole file) |
| ClosedXML | OWN001, `Slice.cs:91,109,149,188,219` (`Enumerator` locals) | **FP** | `Slice.Enumerator.Dispose()` (`Slice.cs:416`) is a **statically empty method body** — verified, no other override, no unmanaged handle in the type; cannot leak anything |

## needs-maintainer-review — explicit list (borderline, not self-certified)

- ShareX: `ColorPickerForm.cs:44` `clipboardStatusHider`, `AboutForm.cs:36`
  `easterEgg`, `MainForm.cs:49` `actionsMenuIconCache` — custom-type Dispose
  semantics not read.
- ShareX: 89 event-subscription own-only findings — not individually verified
  beyond one spot-check.
- MaterialDesignInXamlToolkit: 7 `themeManager.ThemeChanged` subscriptions on
  plain windows/ViewModels (not the `Application` singleton) — plausibly honest
  advisory warnings, not confirmed bugs either way.
- MaterialDesignInXamlToolkit: the `CircleWipe.cs`/`FadeWipe.cs`
  returned-Timeline case — matches an already-fixed idiom, but the shipped
  fix's coverage of this exact single-method shape wasn't confirmed.
- AvalonEdit: `Caret.cs`, `TextAreaAutomationPeer.cs`, `ImeSupport.cs:48` —
  plausible composition-owned back-references, ownership chain not fully traced.

## New patterns → `field-notes-patterns.md`

Entries 11-18 appended (see that file) for every FP-class above that wasn't
already catalogued: DP/property-changed subscription rotation (the single
most-corroborated pattern this run — 3 repos, 6+ sites); WinForms
`Controls`/`ToolStripItemCollection` membership and `IContainer`-registration as
disposal channels; `using (field = new T())`; `Behavior<T>.AssociatedObject`
and self-owned-collection-element as co-lifetime sources; template part via
`FindName`/local pattern variable; `CommandManager.RequerySuggested`'s
weak-reference special case; the self-detaching handler idiom; and the
user-defined no-op-`Dispose()` case (ClosedXML).

## Corpus reduction

One flagship true positive — ShareX's `ShapeManagerMenu`/`menuForm` leak — is
reduced to `corpus/real-world/sharex-shapemanager-menuform-leak/` (verified
against `python tests/test_corpus.py`, `python tests/run_tests.py`, and
`cd rust && cargo test`, all green; `tests/fixtures/cfg_parity.json` regenerated
to match). The other true positives found (ShareX's `HistoryItemManager`
cluster, the Timer/ImageList fields, AvalonEdit's `TextView`) were **not**
reduced to corpus fixtures in this PR — same root-cause shapes as fixtures
already in the corpus (owned-field-never-released), and the time budget went
into triaging the full 5-repo breadth instead. Noted here rather than left
silent, per the honesty requirement.

## Follow-up issues (precision gaps — no analyzer code changed here)

1. [#218](https://github.com/PhysShell/Own.NET/issues/218) — WinForms
   container-membership disposal channels (`Controls.Add`/`AddRange`
   transitive disposal + `IContainer`-registered/`new T(components)` component
   construction) not recognised.
2. [#219](https://github.com/PhysShell/Own.NET/issues/219) — DependencyProperty/
   property-changed old→new subscription rotation (unsub old, sub new, same
   handler) not recognised as a paired subscribe/unsubscribe — confirmed in 3
   separate repos, 6+ call sites; highest-value fix from this sweep.
3. [#220](https://github.com/PhysShell/Own.NET/issues/220) — `using (field = new
   T())` — a field as the direct acquisition target of a `using` statement
   isn't recognised as releasing that field.
4. [#221](https://github.com/PhysShell/Own.NET/issues/221) — Self-owned/
   co-lifetimed source exemption is too narrow — doesn't cover
   `Behavior<T>.AssociatedObject`, an `Application`-derived subscriber whose
   source is an app-scoped (not literal `static`) instance, or subscribing to
   an element of the class's own constructed collection.
5. [#222](https://github.com/PhysShell/Own.NET/issues/222) — Self-owned-
   template-part exemption doesn't cover a template child captured as a local
   (`FindName`/`GetTemplateChild(...) is T x`), only a field assignment —
   confirmed in 2 repos.
6. [#223](https://github.com/PhysShell/Own.NET/issues/223) —
   `CommandManager.RequerySuggested` (and similarly-implemented BCL/WPF events
   built on weak references) should be allowlisted by name, not flagged as a
   hard "static source" error.
7. [#224](https://github.com/PhysShell/Own.NET/issues/224) — A subscribed
   handler whose own body contains a matching `-=` against itself
   (self-detaching on first firing) should be recognised as bounded.
8. [#225](https://github.com/PhysShell/Own.NET/issues/225) — The
   no-op-`Dispose()` exemption (`IsNoOpDisposeWrapper`) should extend from
   named BCL types to any type (first-party or not) whose `Dispose()` method
   body is statically empty.

(Numbering above matches `field-notes-patterns.md` entries 11-19 in spirit but
not 1:1 — issues are grouped by fix surface, e.g. entries 12+13 share issue #218,
entry 15's three sub-shapes share issue #221.)
