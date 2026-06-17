// Fix: subscribe with named handlers (so they have a `-=` handle) and detach them
// in Window_Closing. The view-model no longer roots the window, and a repeated
// Loaded no longer stacks duplicate handlers.
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
