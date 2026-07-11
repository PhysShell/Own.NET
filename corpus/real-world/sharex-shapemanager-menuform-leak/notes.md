# ShareX — the annotation toolbar `Form` is built but never disposed

**Found by the issue #201 oracle sweep** (`docs/notes/oracle-sweep-2026-07-10.md`).
Target: `ShareX/ShareX` @ `0df9ca4`, `ShareX.ScreenCaptureLib/Shapes/ShapeManagerMenu.cs`
(`CreateToolbar`, ~lines 62-1246) and `ShapeManager.cs:2406-2411` (`Dispose`).

**Pattern.** `ShapeManager.CreateToolbar()` builds the on-screen annotation/region-
capture toolbar as a plain `Form` (`menuForm`), hosting a `ToolStripEx` with roughly
38 buttons, menu items, numeric-updowns, and combo-boxes — all created and owned
by `ShapeManager` itself (verified: every one of those ~38 fields is populated in
`CreateToolbar`, and `menuForm.Controls.Add(tsMain)` / `tsMain.Items.Add(...)` wires
them into the same `Form`). `ShapeManager` **does** implement `IDisposable` and
**does** have a real `Dispose()`:

```csharp
public void Dispose()
{
    DeleteAllShapes();
    history.Dispose();
}
```

— but it never disposes, closes, or otherwise releases `menuForm`. Grepping the
whole `ShapeManager` partial class (`ShapeManager.cs` + `ShapeManagerMenu.cs`) turns
up no `menuForm.Dispose()`/`.Close()` call anywhere. Every capture/annotation
session that shows the toolbar leaks a full `Form` and its entire control tree —
a real, non-trivial resource leak (not merely theoretical: `CreateToolbar` is called
fresh each time the toolbar is (re)shown).

**What the checker says (real oracle-sweep extractor output, `--flow-locals`,
`--severity warning`):**

```text
ShapeManagerMenu.cs:47: [OWN001] IDisposable field 'menuForm' (type 'Form') is
  never disposed — its owner 'ShapeManager' leaks it (leak) [resource: disposable field]
```

(plus one OWN001 per never-disposed ToolStrip child field — all transitively real,
since `menuForm` itself is the actual leak root; see the sweep note for the full
count.) Own.NET catches this correctly — cross-checked against the real source, no
`Dispose()`/`Close()` call exists anywhere for `menuForm` in either partial-class
file.

**This `case.own`** models the shape generically: a class's `Dispose()` releases
one owned resource (`history`, standing in for the real `HistoryStack`/`history`
field) but never touches a second one it also owns (`menuForm`) — the plain
owned-field-never-released OWN001, same core logic as the rest of the field-dispose
corpus. As with the rest of the corpus, `case.own` is a hand reduction of the C#
pattern (one representative field standing in for the ~38 that all share the same
root cause), not a line-for-line transcription of `ShapeManagerMenu.cs`.

**Draft verdict: true positive**, per the issue #201 sweep's triage guardrails
(final TP/FP confirmation is the maintainer's call; this is not itself a bug report
filed against ShareX upstream — see `docs/notes/mining.md`'s "reporting upstream is
a separate, manual step").
