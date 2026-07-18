// Fix: subscribe with named handlers (so they have a `-=` handle) and detach them
// in Window_Closing, wired IN CODE (`Closing += Window_Closing`). The view-model
// no longer roots the window, and a repeated Loaded no longer stacks duplicate
// handlers.
//
// The code wiring is load-bearing (#278 follow-up): a `Window_Closing`-style NAME
// alone proves nothing to the extractor (the XAML attach never reaches it, and a
// bare name may be stale dead code), so the release is credited only because the
// ctor provably attaches the handler to the window's own Closing event.
using System;
using System.Windows;

public partial class VideoSource : Window
{
    private readonly VideoSourceViewModel _viewModel;

    public VideoSource()
    {
        InitializeComponent();
        _viewModel = DataContext as VideoSourceViewModel;
        Closing += Window_Closing;
    }

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
}

// Minimal in-file stand-ins so the reduction is self-contained (mirrors before.cs).
// With the events resolvable, the matching `-=` in Window_Closing releases each
// subscription, so the extractor stays silent — the fix is clean.
public sealed class VideoSourceViewModel
{
    public event EventHandler ShowErrorRequested;
    public event EventHandler HideErrorRequested;
    public event EventHandler CloseRequested;
}

internal static class StatusBand
{
    public static void Error(string message) { }
    public static void Hide() { }
}
