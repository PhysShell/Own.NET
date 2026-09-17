// BUGGY (synthetic conformance, P-036 §Phase 2 fixture 6 — the cleanup target
// is an injected INTERFACE; the only implementation in reach is a no-op).
// Dispose delegates to `_cleanup.Run()`; nothing here proves that call ever
// detaches the handler. The subscription leaks. The honest verdict for a tool
// that cannot resolve the target is "unproven release" (degraded), never clean.
using System;
using System.ComponentModel;

public interface ICleanup
{
    void Run();
}

public sealed class NoopCleanup : ICleanup
{
    public void Run() { }
}

public sealed class Report : IDisposable
{
    private readonly INotifyPropertyChanged _properties;   // injected, unknown lifetime
    private readonly ICleanup _cleanup;                     // injected, unresolved target

    public Report(INotifyPropertyChanged properties, ICleanup cleanup)
    {
        _properties = properties;
        _cleanup = cleanup;
        _properties.PropertyChanged += OnPropertiesChanged;
    }

    public void Dispose()
    {
        _cleanup.Run();                                     // virtual target: proves nothing
    }

    private void OnPropertiesChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}
