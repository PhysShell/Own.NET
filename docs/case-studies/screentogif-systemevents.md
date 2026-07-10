# Case study: subscribing to a process, not a window (ScreenToGif)

**Target:** [`NickeManarin/ScreenToGif`](https://github.com/NickeManarin/ScreenToGif)
@ `27a49c3` — the same pattern independently, twice:
`ScreenToGif/Windows/Other/GraphicsConfigurationDialog.xaml.cs:35` and
`ScreenToGif/Windows/Other/Troubleshoot.xaml.cs:27`. Found by mining after
turning on the WPF profile
([`docs/notes/real-world-mining.md`](../notes/real-world-mining.md)).

## Bad

```csharp
public partial class GraphicsConfigurationDialog : Window
{
    public GraphicsConfigurationDialog()
    {
        InitializeComponent();
        SystemEvents.DisplaySettingsChanged += SystemEvents_DisplaySettingsChanged;
        // ...never `-=`'d
    }

    private void SystemEvents_DisplaySettingsChanged(object sender, EventArgs e) { }
}
```

`Microsoft.Win32.SystemEvents` is a **static class** — its events live for the
entire process, not for any window. Subscribing a dialog's method-group handler
to it hands the static event a strong reference to the dialog, and nothing
ever gives it back. The dialog can be closed a hundred times over; the process
keeps every instance alive until it exits. This is the textbook `SystemEvents`
leak the .NET docs carry an explicit warning about — and it occurs twice in
this codebase, independently, in two unrelated dialogs.

## Fixed

Unsubscribe when the window is done — here, on `Closed`:

```csharp
public GraphicsConfigurationDialog()
{
    InitializeComponent();
    SystemEvents.DisplaySettingsChanged += SystemEvents_DisplaySettingsChanged;
    Closed += OnClosed;
}

private void OnClosed(object sender, EventArgs e)
{
    SystemEvents.DisplaySettingsChanged -= SystemEvents_DisplaySettingsChanged;
    Closed -= OnClosed;
}
```

Breaking the static source's hold is enough — the dialog goes back to being
collectable exactly when it should.

## What others miss

Same story as the [`VideoSource` case](screentogif-videosource.md): nothing here
is ever "not disposed," so `IDisposableAnalyzers`/`CA2213`/CodeQL's
`cs/local-not-disposed` have no defect to find — the cross-tool run
([`docs/notes/oracle.md`](../notes/oracle.md)) confirms CodeQL flags neither
site on this commit; its query set doesn't have "event subscribed to a static
source, never unsubscribed." What makes this pair worth its own write-up next
to `VideoSource`, rather than folding into it, is the **severity**: here Own.NET
does not hedge.

## How Own reports it

Real extractor output (P-001), WPF reference pack **on** (needed to resolve
`SystemEvents` as a framework type):

```text
GraphicsConfigurationDialog.xaml.cs:35: error: [OWN001] event
  'SystemEvents.DisplaySettingsChanged' is subscribed (handler
  'SystemEvents_DisplaySettingsChanged') but never unsubscribed — the source keeps
  'GraphicsConfigurationDialog' alive (leak) [resource: subscription token]
```

**Why error, not warning — the tiering.** The `VideoSource` finding next door is
a *warning* because its subscription source is an injected field of unknown
lifetime — Own.NET can't prove it outlives the window. Here the source is
`static`: it provably outlives every window in the process, so the P-004
severity tiering classifies it accordingly and the same shape (subscribe,
never unsubscribe) escalates to a hard **error**, not a hedge. The extractor
draws that line from the source's *provable* lifetime, not from a blanket rule
about events — the two case studies are the same defect class reported at two
different confidence levels, on purpose.

Regression-locked as `corpus/real-world/screentogif-systemevents-leak/`
(`before.cs`/`after.cs`, pinned by `tests/test_corpus.py`).
