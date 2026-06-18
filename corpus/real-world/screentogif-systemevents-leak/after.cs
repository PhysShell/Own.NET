// Fix: unsubscribe when the window is done (here, on Closed), breaking the static
// source's hold so the window can be collected.
using System;
using System.Windows;
using Microsoft.Win32;

public partial class GraphicsConfigurationDialog : Window
{
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

    private void SystemEvents_DisplaySettingsChanged(object sender, EventArgs e) { }
}
