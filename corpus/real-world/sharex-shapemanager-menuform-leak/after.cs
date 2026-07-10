// Fix: Dispose() also disposes menuForm (a Form is IDisposable; disposing it
// tears down its whole child-control tree, per WinForms' own Control.Dispose
// semantics — see field-notes-patterns.md for that transitive-disposal idiom).
using System;
using System.Windows.Forms;

internal sealed class ShapeManager : IDisposable
{
    private Form menuForm;
    private readonly HistoryStack history = new HistoryStack();

    internal void CreateToolbar()
    {
        menuForm = new Form { ShowInTaskbar = false };
        menuForm.Show();
    }

    public void Dispose()
    {
        history.Dispose();
        menuForm?.Dispose();
    }
}

internal sealed class HistoryStack : IDisposable
{
    public void Dispose() { }
}
