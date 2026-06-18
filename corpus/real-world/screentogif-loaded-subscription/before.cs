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
