// BUGGY (#278 follow-up, blocker 2; hand-reduced into case.own).
//
// The ctor subscribes to an injected publisher; the matching `-=` sits in a
// method NAMED like a XAML-wired lifecycle handler (`Window_Closing`) — but
// NOTHING in code attaches it to any event. The name alone proves nothing:
// XAML attaches never reach the extractor, and a handler-shaped name with no
// wiring may equally be stale dead code left behind after the XAML attribute
// was removed. Crediting the naming convention was a silent false-negative
// path in the first #278 slice.
//
// own-check MUST flag this OWN001; a XAML-aware slice may later credit a REAL
// XAML attach with actual evidence.
using System;
using System.ComponentModel;

public sealed class SettingsView
{
    private readonly INotifyPropertyChanged _settings;   // injected, unknown lifetime

    public SettingsView(INotifyPropertyChanged settings)
    {
        _settings = settings;
        _settings.PropertyChanged += OnSettingsChanged;
    }

    private void Window_Closing(object sender, EventArgs e)
    {
        _settings.PropertyChanged -= OnSettingsChanged;   // nothing wires this handler
    }

    private void OnSettingsChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}
