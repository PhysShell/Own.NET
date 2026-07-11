// Reduced from ShareX/ShareX @ 0df9ca4, ShareX.ScreenCaptureLib/Shapes/ShapeManagerMenu.cs
// (CreateToolbar, ~lines 62-1246) and ShapeManager.cs:2406-2411 (Dispose) — found by
// the issue #201 oracle sweep.
//
// ShapeManager builds its on-screen annotation toolbar as a plain WPF-Forms `Form`
// (`menuForm`) hosting a `ToolStripEx` with ~38 buttons/menu items/numeric-updowns/
// combo-boxes, all created and owned by this class. `ShapeManager.Dispose()` exists
// and disposes some of what the class owns (`history`), but forgets `menuForm`
// entirely — every capture/annotation session leaks a full `Form` plus its whole
// toolbar tree, because nothing else ever closes or disposes it either.
using System;
using System.Windows.Forms;

internal sealed class ShapeManager : IDisposable
{
    private Form menuForm;
    private readonly HistoryStack history = new HistoryStack();

    internal void CreateToolbar()
    {
        menuForm = new Form { ShowInTaskbar = false };
        // ...builds tsMain and ~38 ToolStrip child items, all added to menuForm...
        menuForm.Show();
    }

    public void Dispose()
    {
        // real code also calls DeleteAllShapes(); irrelevant to the leak.
        history.Dispose();
        // menuForm is never disposed or closed anywhere in this class.
    }
}

internal sealed class HistoryStack : IDisposable
{
    public void Dispose() { }
}
