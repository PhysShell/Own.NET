using System;

namespace Own.Samples;

// Issue #219 — WinForms disposal CHANNELS the field-disposal scan didn't recognise:
//   (a) a Control/ToolStripItem field added to THIS's own Controls/Items collection is disposed
//       transitively by Control.Dispose(bool) (the framework's designer contract), when the class
//       itself reaches a disposal root (a designer `Dispose(bool)` calling `base.Dispose(disposing)`);
//   (b) a component constructed with the designer `IContainer` (`new T(components)`) or explicitly
//       `components.Add(x)` is disposed by `components.Dispose()`.
// Confirmed FP in ShareX, ~30 sites. Negative controls prove the fix does not over-widen.
//
// Stand-ins for System.Windows.Forms (the extractor build has no WindowsDesktop ref) — same shapes.

public sealed class ControlCollection
{
    public void Add(Control c) { }
    public void AddRange(Control[] cs) { }
}

public class Control : IDisposable
{
    public ControlCollection Controls { get; } = new ControlCollection();
    protected virtual void Dispose(bool disposing) { }
    public void Dispose() { Dispose(true); }
}

public sealed class Label : Control { }
public sealed class Button : Control { }

// A ComboBox/ListBox `Items` is an ObjectCollection that does NOT dispose its items — used by a
// negative control so `Items` is only a disposal channel for a real ToolStripItemCollection.
public sealed class ObjectCollection
{
    public void Add(object item) { }
}

public sealed class ComboBox : Control
{
    public ObjectCollection Items { get; } = new ObjectCollection();
}

// Stand-ins for System.ComponentModel.IContainer / Container (the designer `components` sink),
// matched by simple name. `Add` has the plain and the named (`Add(x, "name")`) overloads.
public interface IContainer : IDisposable
{
    void Add(object component);
    void Add(object component, string name);
}

public sealed class Container : IContainer
{
    public void Add(object component) { }
    public void Add(object component, string name) { }
    public void Dispose() { }
}

public sealed class ToolStripItemCollection
{
    public void Add(ToolStripItem i) { }
    public void AddRange(ToolStripItem[] items) { }
}

public class ToolStripItem : IDisposable { public void Dispose() { } }
public sealed class ToolStripMenuItem : ToolStripItem { }

public sealed class ContextMenuStrip : Control
{
    public ToolStripItemCollection Items { get; } = new ToolStripItemCollection();
}

public sealed class NotifyIcon : IDisposable
{
    public NotifyIcon() { }
    public NotifyIcon(IContainer container) { }   // the designer registration overload
    public void Dispose() { }
}

// ---- (a) Controls/Items membership + (b) IContainer registration — all SILENT ----
// A designer-generated Form-like control: reaches a disposal root via `base.Dispose(disposing)`.
public sealed class MainForm : Control
{
    private readonly IContainer components = new Container();
    private Label lblStatus;
    private Button btnOk;
    private ContextMenuStrip menu;
    private ToolStripMenuItem menuItem;
    private NotifyIcon trayIcon;
    private NotifyIcon unregisteredIcon;   // NEGATIVE CONTROL (b): NOT container-registered

    public MainForm()
    {
        lblStatus = new Label();
        btnOk = new Button();
        menu = new ContextMenuStrip();
        menuItem = new ToolStripMenuItem();
        this.Controls.Add(this.lblStatus);                       // (a) direct -> SILENT
        this.Controls.AddRange(new Control[] { this.btnOk });    // (a) AddRange -> SILENT
        this.Controls.Add(this.menu);                            // menu reaches root (added to this.Controls)
        this.menu.Items.Add(this.menuItem);                      // (a) transitive via a rooted container -> SILENT
        trayIcon = new NotifyIcon(components);                   // (b) new T(components) -> SILENT
        unregisteredIcon = new NotifyIcon();                     // NOT registered -> LEAK (control b)
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) components?.Dispose();
        base.Dispose(disposing);   // reaches the disposal root: Control.Dispose(bool) disposes Controls
    }
}

// A component explicitly registered via components.Add(x) (the other (b) shape) -> SILENT.
public sealed class RegisteredComponentForm : Control
{
    private readonly Container components = new Container();
    private NotifyIcon icon;

    public RegisteredComponentForm()
    {
        icon = new NotifyIcon();
        components.Add(this.icon);   // (b) explicit registration -> SILENT
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) components.Dispose();
        base.Dispose(disposing);
    }
}

// A component registered through the NAMED IContainer overload `components.Add(x, "name")` is
// disposed by components.Dispose() just like the single-arg form -> SILENT.
public sealed class NamedRegistrationForm : Control
{
    private readonly Container components = new Container();
    private NotifyIcon namedIcon;

    public NamedRegistrationForm()
    {
        namedIcon = new NotifyIcon();
        components.Add(this.namedIcon, "tray");   // (b) named registration -> SILENT
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) components.Dispose();
        base.Dispose(disposing);
    }
}

// ---- NEGATIVE CONTROLS ----

// (a) FOREIGN container: the child is added to a container passed in as a PARAMETER, not THIS's own
// Controls -> not a disposal channel for this class -> STAYS FLAGGED.
public sealed class ForeignContainerAdder : Control
{
    private Label lblForeign;

    public void AttachTo(Control other)
    {
        lblForeign = new Label();
        other.Controls.Add(this.lblForeign);   // added to a FOREIGN (param) container -> LEAK
    }

    protected override void Dispose(bool disposing) { base.Dispose(disposing); }
}

// (a) Codex P2: a ComboBox/ListBox `Items` is an ObjectCollection that does NOT dispose its items,
// so a real IDisposable stored as a combo item still leaks even though the combo itself is disposed
// (added to this.Controls). Only a ToolStripItemCollection's Items is a disposal channel.
public sealed class ComboItemForm : Control
{
    private ComboBox combo;
    private NotifyIcon comboItem;   // a real disposable stored as a combo item

    public ComboItemForm()
    {
        combo = new ComboBox();
        comboItem = new NotifyIcon();
        this.Controls.Add(this.combo);       // combo IS disposed (Controls channel) -> silent
        combo.Items.Add(this.comboItem);     // ComboBox.Items does NOT dispose it -> LEAK
    }

    protected override void Dispose(bool disposing) { base.Dispose(disposing); }
}

// (a) NO disposal root: a plain owner (not framework-managed) builds a menu but has NO Dispose at
// all, so its owned container is never disposed -> both the container and its child STAY FLAGGED
// (the ShareX HistoryItemManager true-positive shape).
public sealed class MenuOwnerNoDispose
{
    private ContextMenuStrip cms = new ContextMenuStrip();
    private ToolStripMenuItem item;

    public MenuOwnerNoDispose()
    {
        item = new ToolStripMenuItem();
        cms.Items.Add(this.item);   // owned container never disposed (no Dispose) -> LEAK
    }
}
