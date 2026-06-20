// Reduced from NickeManarin/ScreenToGif @ 27a49c3,
// ScreenToGif/Windows/Other/VideoSource.xaml.cs:46-90 — found by mining (P-004).
//
// A Window subscribes lambdas to its view-model's events in Window_Loaded and
// never detaches them. Two problems: (1) Loaded can fire more than once (the
// element is re-added to the visual tree) -> duplicate handlers stack up; (2) the
// lambdas capture `this`, so the view-model holds the window alive for as long as
// the view-model itself is reachable. There is no `-=` anywhere in the file.
using System;
using System.Windows;

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
        // ...never unsubscribed -> OWN001 (handler leak)
    }

    // Present in the real file, but it does NOT detach the handlers above.
    private void Window_Closing(object sender, System.ComponentModel.CancelEventArgs e) { }
}

// Minimal in-file stand-ins so the reduction is self-contained. The real
// VideoSourceViewModel lives elsewhere in ScreenToGif, so in isolation the
// type-aware extractor cannot bind `_viewModel.ShowErrorRequested` to an event
// and honestly emits OWN050 (unresolved) instead of the OWN001 subscription leak
// — which the benchmark scored as a miss. With the type resolvable, the extractor
// flags the leak (warning-tier: an injected `DataContext` source it cannot prove
// outlives the window), exactly as it does on the full repo.
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
