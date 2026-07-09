# Case study: a view that outlives its close button (ScreenToGif)

**Target:** [`NickeManarin/ScreenToGif`](https://github.com/NickeManarin/ScreenToGif)
@ `27a49c3`, `ScreenToGif/Windows/Other/VideoSource.xaml.cs:50-83`. Found by the
first real-world mining run
([`docs/notes/real-world-mining.md`](../notes/real-world-mining.md), milestone 1)
— unmodified, un-cherry-picked OSS code, not a constructed example.

## Bad

A `Window` reads its view-model out of `DataContext`, then wires four inline
lambdas to the view-model's custom events inside `Window_Loaded`:

```csharp
public partial class VideoSource : Window
{
    private readonly VideoSourceViewModel _viewModel;

    public VideoSource()
    {
        InitializeComponent();
        _viewModel = DataContext as VideoSourceViewModel;
    }

    private void Window_Loaded(object sender, RoutedEventArgs e)
    {
        _viewModel.ShowErrorRequested += (_, args) => StatusBand.Error(args?.ToString());
        _viewModel.HideErrorRequested += (_, _) => StatusBand.Hide();
        _viewModel.CloseRequested += (_, _) => DialogResult = true;
        // ...never unsubscribed
    }

    // Present in the real file, but it does NOT detach the handlers above.
    private void Window_Closing(object sender, System.ComponentModel.CancelEventArgs e) { }
}
```

`Window_Closing` exists — it just doesn't undo the subscriptions. Two distinct
bugs fall out of that one omission: the lambdas capture `this`, so the
view-model holds a strong reference to the window for as long as the
view-model itself is reachable; and because WPF's `Loaded` can fire more than
once (an element re-added to the visual tree re-raises it), the handlers can
**stack**, so `ShowErrorRequested` fires the same status-band update twice, then
three times, once per reload.

## Fixed

Give each subscription a named handler — the thing an inline lambda doesn't
have — and detach it where `Window_Closing` already runs:

```csharp
private void Window_Loaded(object sender, RoutedEventArgs e)
{
    _viewModel.ShowErrorRequested += OnShowError;
    _viewModel.HideErrorRequested += OnHideError;
    _viewModel.CloseRequested += OnClose;
}

private void Window_Closing(object sender, System.ComponentModel.CancelEventArgs e)
{
    _viewModel.ShowErrorRequested -= OnShowError;
    _viewModel.HideErrorRequested -= OnHideError;
    _viewModel.CloseRequested -= OnClose;
}

private void OnShowError(object sender, EventArgs args) => StatusBand.Error(args?.ToString());
private void OnHideError(object sender, EventArgs e) => StatusBand.Hide();
private void OnClose(object sender, EventArgs e) => DialogResult = true;
```

No behavior change, no new fields — the fix is entirely "have a handle to
unsubscribe with, and use it in the close path that was already there."

## What others miss

This is a **view ↔ view-model lifetime** shape: an `IDisposable`/dispose-not-called
analyzer has nothing to check here, because neither side of the subscription
implements `IDisposable` and nothing is ever "not disposed" — the leak is a
plain C# event, the kind `CA2213`/`IDisposableAnalyzers`/CodeQL's
`cs/local-not-disposed` don't model at all. Cross-checked against CodeQL on the
same commit ([`docs/notes/oracle.md`](../notes/oracle.md)): its findings on
ScreenToGif are entirely the Dispose/RAII class (`OpenFileDialog`, `Pen`,
`Bitmap`, …); it flags none of the four `VideoSource` subscriptions, because its
query set has no "event subscribed, never unsubscribed" rule. Own.NET and CodeQL
are complementary here, not redundant — see the
[Dispose-agreement case study](dispose-agreement-with-codeql.md) for where they
*do* overlap.

## How Own reports it

Real extractor output (P-001), WPF reference pack off — these events are the
app's own types, so they resolve without it:

```text
VideoSource.xaml.cs:50: warning: [OWN001] event '_viewModel.ShowErrorRequested' is
  subscribed (handler '(_, args) => ...') but never unsubscribed; its source is an
  injected dependency whose lifetime is unknown, so it may outlive and keep
  'VideoSource' alive (possible leak — and being an inline lambda it has no '-='
  handle, so it could never be detached) [resource: subscription token]
```

**Why warning, not error — the honest part.** `_viewModel` is an injected field;
Own.NET's source tiering can't *prove* it outlives the window (in fact, as the
window's own `DataContext`, the two likely share a lifetime — a collectable
cycle, not necessarily a leaked one). So the verdict is "possible leak," not a
hard error — the duplicate-handler-on-reload bug is real regardless, and the
diagnostic says so explicitly (an inline lambda has no `-=` handle, full stop).
Contrast the [SystemEvents case study](screentogif-systemevents.md), where the
subscription source is `static` and the same shape escalates to a hard error.

Regression-locked as `corpus/real-world/screentogif-loaded-subscription/`
(`before.cs`/`after.cs`, pinned by `tests/test_corpus.py`).
