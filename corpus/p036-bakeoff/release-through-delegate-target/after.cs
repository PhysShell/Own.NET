// FIXED (synthetic conformance). The cleanup is a delegate field whose target
// is statically known — the class's own `Detach`, assigned in the constructor
// and never reassigned. Dispose invokes it, so the `-=` provably runs.
// A tool that cannot resolve delegate targets keeps a warning here (degraded
// precision, an honest false positive); a tool that resolves the statically
// known target is silent.
using System;
using System.ComponentModel;

public sealed class Report : IDisposable
{
    private readonly INotifyPropertyChanged _properties;   // injected, unknown lifetime
    private readonly Action _cleanup;

    public Report(INotifyPropertyChanged properties)
    {
        _properties = properties;
        _properties.PropertyChanged += OnPropertiesChanged;
        _cleanup = Detach;                                  // statically known target
    }

    public void Dispose()
    {
        _cleanup();                                         // runs Detach
    }

    private void Detach()
    {
        _properties.PropertyChanged -= OnPropertiesChanged;
    }

    private void OnPropertiesChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}
