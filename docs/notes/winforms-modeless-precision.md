# WinForms modeless-`Form` precision — the framework owns a `.Show()`'d form

A precision fix driven by mining **ShareX** (a large, real WinForms app) with the
`--flow-locals` local-`IDisposable` detector. The hunt's honest deliverable was a
*precision-hardening backlog*, not a pile of real bugs: our detector was tuned on
WPF, and WPF and WinForms differ on **who owns a window's lifetime**. This note is
the first item off that backlog.

## The false-positive class

The flow detector flags a local `IDisposable` that is constructed and never
disposed (OWN001). On WinForms that over-fires on the single most idiomatic line in
the framework:

```csharp
void OpenSettings()
{
    var form = new SettingsForm();   // SettingsForm : System.Windows.Forms.Form
    form.Show();                     // modeless — returns immediately
}
```

`form` is a `Form` (an `IDisposable`), constructed, used, and never disposed — so
the WPF-tuned detector calls it a leak. **It is not.** `Control.Show()` opens the
form *modeless*: the window stays open after the method returns, and **WinForms
itself disposes the form when the user closes it** (the framework owns the
lifetime). Disposing it yourself in `OpenSettings` would be a bug — you'd dispose a
window that is still on screen. This shape is everywhere in a WinForms app (every
"open a tool window" handler), so the FP is not incidental; it is systematic.

The contrast is a **modal** dialog:

```csharp
var dlg = new ConfirmDialog();
dlg.ShowDialog();                    // modal — blocks, returns a DialogResult
// dlg is the CALLER's to dispose here — leaked if never disposed
```

`ShowDialog()` blocks and returns; the caller owns the dialog and **must** dispose
it (the canonical `using var dlg = new ConfirmDialog();` pattern). An undisposed
`ShowDialog()`'d form *is* a real leak — and must stay flagged.

So the discriminator is exactly the show method: **`Show()` → framework-owned;
`ShowDialog()` → caller-owned (tracked).**

## The fix — `Show()` is a release at the call site

The first cut dropped a `Form` local from the tracked set whenever a `local.Show()`
appeared *anywhere* in the method body — a method-wide exemption. That is not
path-sensitive: `var f = new Form(); if (open) f.Show();` would go silent even though
the `open == false` path constructs a form that is never handed to WinForms and never
disposed (a real leak). Codex flagged exactly this (PR #57 review).

The right model is the project's own **call-site release** shape — the same one the
pool `Return` and the inter-procedural consume contract already use: a modeless
`local.Show()` *transfers ownership to the framework on that path*, so the flow
detector emits a **`release` of the local at the show site**. One helper plus one
branch in the flow lowering (`EmitFlowExpr`):

```csharp
// System.Windows.Forms.Form or a subclass (semantic, walks the base chain).
static bool DerivesFromWinFormsForm(ITypeSymbol? t)
{
    for (var b = t; b is not null; b = b.BaseType)
        if (b.Name == "Form" && b.ContainingNamespace?.ToString() == "System.Windows.Forms")
            return true;
    return false;
}

// in EmitFlowExpr, alongside the Dispose()/Close()/pool-Return/consume releases:
// x.Show() on a tracked Form-derived local -> release (ownership -> framework).
if (expr is InvocationExpressionSyntax sinv
    && sinv.Expression is MemberAccessExpressionSyntax sma
    && sma.Name.Identifier.Text == "Show"
    && sma.Expression is IdentifierNameSyntax sid
    && tracked.Contains(sid.Identifier.Text)
    && DerivesFromWinFormsForm(model.GetTypeInfo(sma.Expression).Type))
{
    nodes.Add(new { op = "release", var = sid.Identifier.Text, line = LineOf(sinv) });
    return;
}
```

Because the release lands *on the show path*, the flow engine does the rest
path-sensitively:

- `var f = new Form(); f.Show();` — acquire + release → balanced → **silent**;
- `var f = new Form(); if (open) f.Show();` — released on the `then` path, not the
  `else` → **OWN001 "may not be disposed on every path"** (the leak the method-wide
  exemption hid);
- `var d = new Form(); d.ShowDialog();` — `ShowDialog` is **not** matched (only
  `Show`), so it stays a tracked *use* → an undisposed modal dialog is still
  **OWN001**.

It is `Show()`-only and `Form`-derived-guarded, so a `ShowDialog()`'d form and any
non-`Form` disposable with a `Show()` method are untouched. No core change — it reuses
the existing `release` op exactly as the other call-site-release branches do.

## Pinned in CI (validated where the frontend always is)

The fix lands *with* `frontend/roslyn/samples/WinFormsModelessSample.cs`, wired into
the `wpf-extractor` job's `--flow-locals` steps. It is **self-contained**: a stub
`namespace System.Windows.Forms { public class Form : System.IDisposable { … } }`
stands in for the framework type (the WinForms reference pack is not loaded in that
step), matched by simple name + namespace exactly as the real one is. The sample
asserts the whole discriminator, path-sensitivity included:

- `OpenModeless` — `new ModelessForm().Show()` → **silent** (ownership → framework;
  the FP the fix removes);
- `OpenModelessConditional` — `if (open) condForm.Show()` → **OWN001** (`'condForm'
  may not be disposed on every path` — the no-show path leaks; pins the
  path-sensitivity Codex asked for);
- `OpenModalLeak` — `new ModalDialog().ShowDialog()`, never disposed → **OWN001**
  (`'modalLeak' is never disposed`, caller-owned leak — stays flagged);
- `OpenModalOk` — the same modal dialog disposed on every path → **silent** (proving
  the leak above is about *disposal*, not poisoned by `ShowDialog` itself).

The Python-core half (facts → verdict) was validated locally on the hand-built flow
facts before pushing; the C# half (source → facts) is validated in CI by the sample,
the same place the rest of the frontend is.

## Scope and the rest of the backlog

This closes the one systematic WinForms FP — modeless forms — with a tight,
`Show()`-only call-site release. The broader WinForms ownership story (a `Control` added to a
parent's `Controls` collection is disposed by the parent; `components`-container
disposal) is a separate slice on the precision backlog the ShareX hunt produced, to
be taken the same way: one FP class, one sample, one CI pin.
