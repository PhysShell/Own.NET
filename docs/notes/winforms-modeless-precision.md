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

So the discriminator is exactly the show method: **`Show()` → framework-owned
(exempt); `ShowDialog()` → caller-owned (tracked).**

## The fix

Two helpers in the extractor (`frontend/roslyn/OwnSharp.Extractor/Program.cs`), and
one extra guard on the flow-candidate condition — a local is dropped from the
tracked set when it is a `Form`-derived type shown modeless in the method body:

```csharp
// System.Windows.Forms.Form or a subclass (semantic, walks the base chain).
static bool DerivesFromWinFormsForm(ITypeSymbol? t)
{
    for (var b = t; b is not null; b = b.BaseType)
        if (b.Name == "Form" && b.ContainingNamespace?.ToString() == "System.Windows.Forms")
            return true;
    return false;
}

// A Form-derived local shown *modeless* (`local.Show()`) in the method body. A modal
// `local.ShowDialog()` is deliberately NOT matched, so it stays tracked (caller-owned).
static bool IsModelessShownForm(string name, BlockSyntax body, ITypeSymbol type) =>
    DerivesFromWinFormsForm(type)
    && body.DescendantNodes().OfType<InvocationExpressionSyntax>().Any(inv =>
        inv.Expression is MemberAccessExpressionSyntax
        {
            Name.Identifier.Text: "Show",
            Expression: IdentifierNameSyntax { Identifier.Text: var recv },
        } && recv == name);

// in the --flow-locals candidate loop, the ObjectCreation branch:
//   && ImplementsIDisposable(dt) && !IsDisposeOptional(dt)
//   && !IsModelessShownForm(v.Identifier.Text, mbody, dt)
```

The guard is **per-local and `Show()`-only** by design: it exempts only the
specific local whose receiver appears in a `.Show()` call, and only when the type
actually derives from `System.Windows.Forms.Form`. A `ShowDialog()`'d form, a
`Form` constructed but never shown, and any non-`Form` disposable are all
untouched. It composes with the existing `IsDisposeOptional` exemptions exactly as
the pool/factory branches do — a narrowing of the candidate set, no new finding
path, no core change.

## Pinned in CI (validated where the frontend always is)

The fix lands *with* `frontend/roslyn/samples/WinFormsModelessSample.cs`, wired into
the `wpf-extractor` job's `--flow-locals` steps. It is **self-contained**: a stub
`namespace System.Windows.Forms { public class Form : System.IDisposable { … } }`
stands in for the framework type (the WinForms reference pack is not loaded in that
step), matched by simple name + namespace exactly as the real one is. The sample
asserts the whole discriminator:

- `OpenModeless` — `new ModelessForm().Show()` → **silent** (framework-owned; the FP
  the fix removes);
- `OpenModalLeak` — `new ModalDialog().ShowDialog()`, never disposed → **OWN001**
  (`'modalLeak' is never disposed`, caller-owned leak — stays flagged);
- `OpenModalOk` — the same modal dialog disposed on every path → **silent** (proving
  the leak above is about *disposal*, not poisoned by `ShowDialog` itself).

The Python-core half (facts → verdict) was validated locally on the hand-built flow
facts before pushing; the C# half (source → facts) is validated in CI by the sample,
the same place the rest of the frontend is.

## Scope and the rest of the backlog

This closes the one systematic WinForms FP — modeless forms — with a tight,
`Show()`-only guard. The broader WinForms ownership story (a `Control` added to a
parent's `Controls` collection is disposed by the parent; `components`-container
disposal) is a separate slice on the precision backlog the ShareX hunt produced, to
be taken the same way: one FP class, one sample, one CI pin.
