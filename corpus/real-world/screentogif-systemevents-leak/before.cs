// Reduced from NickeManarin/ScreenToGif @ 27a49c3 — two independent occurrences of
// the same pattern, found by mining (P-004):
//   ScreenToGif/Windows/Other/GraphicsConfigurationDialog.xaml.cs:35
//   ScreenToGif/Windows/Other/Troubleshoot.xaml.cs:27
//
// A Window subscribes to Microsoft.Win32.SystemEvents — a STATIC, process-lifetime
// event source — and never unsubscribes. The static source holds a strong
// reference to the handler's owner (the Window) for the entire life of the
// process: the window closes, but it cannot be collected. This is the textbook
// SystemEvents leak (the docs explicitly warn about it).
using System;
using System.Windows;
using Microsoft.Win32;

public partial class GraphicsConfigurationDialog : Window
{
    public GraphicsConfigurationDialog()
    {
        InitializeComponent();
        SystemEvents.DisplaySettingsChanged += SystemEvents_DisplaySettingsChanged;
        // ...never `-=`'d -> the process-lived SystemEvents pins this dialog (OWN001, error)
    }

    private void SystemEvents_DisplaySettingsChanged(object sender, EventArgs e) { }
}
