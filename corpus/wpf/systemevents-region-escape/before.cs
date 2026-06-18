// BUGGY (the canonical SystemEvents leak, hand-reduced into case.own).
//
// A Window-scoped dialog subscribes itself to Microsoft.Win32.SystemEvents — a
// STATIC, process-lifetime event source — with a strong method-group handler and
// keeps no unsubscribe token. The static source is reachable from a
// process-lifetime GC root, and through the strong delegate so is the dialog: the
// dialog is *promoted* to process lifetime. Close the window all you want -- it
// lives until the process exits. The lifetime mismatch (the dialog expected
// Window scope, actually gets Process scope) is the leak.
//
// Seen here through the REGION model (OWN014, region escape); the same bug viewed
// through the token model (OWN001, owned-but-not-released) is in
// corpus/real-world/screentogif-systemevents-leak. Distilled from
// NickeManarin/ScreenToGif (GraphicsConfigurationDialog / Troubleshoot).
using System;
using System.Windows;
using Microsoft.Win32;

public partial class GraphicsConfigurationDialog : Window
{
    public GraphicsConfigurationDialog()
    {
        InitializeComponent();
        // strong subscription to a process-lived static event, no token kept
        // -> the Window-scoped dialog is promoted to Process lifetime (region escape)
        SystemEvents.DisplaySettingsChanged += OnDisplaySettingsChanged;
    }

    private void OnDisplaySettingsChanged(object? sender, EventArgs e) { /* ... */ }
}
