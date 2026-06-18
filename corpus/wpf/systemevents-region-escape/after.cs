// FIXED. The subscription is released when the window is done (on Closed),
// breaking the static source's strong hold so the dialog drops back to its
// intended Window lifetime and is collectable. A disposable-token form works too
// (see corpus/wpf/viewmodel-escapes-to-app/after.cs); either way the region check
// then sees a release path and stays quiet — no promotion, no OWN014.
using System;
using System.Windows;
using Microsoft.Win32;

public partial class GraphicsConfigurationDialog : Window
{
    public GraphicsConfigurationDialog()
    {
        InitializeComponent();
        SystemEvents.DisplaySettingsChanged += OnDisplaySettingsChanged;
        Closed += OnClosed;
    }

    private void OnClosed(object? sender, EventArgs e)
    {
        // release path -> dialog no longer promoted to Process lifetime
        SystemEvents.DisplaySettingsChanged -= OnDisplaySettingsChanged;
        Closed -= OnClosed;
    }

    private void OnDisplaySettingsChanged(object? sender, EventArgs e) { /* ... */ }
}
