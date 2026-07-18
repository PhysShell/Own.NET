// FIXED. The release moved to Dispose — a deterministic teardown the OWNER
// calls, which does not depend on the object first becoming unreachable. (A
// finalizer may still exist for unmanaged state; it just cannot be the
// subscription's release path.)
//
// own-check MUST treat this as released (silent).
using System;
using System.ComponentModel;

public sealed class FinalizerDetachDocument : IDisposable
{
    private readonly INotifyPropertyChanged _properties;   // injected, unknown lifetime

    public FinalizerDetachDocument(INotifyPropertyChanged properties)
    {
        _properties = properties;
        _properties.PropertyChanged += OnPropertiesChanged;
    }

    public void Dispose()
    {
        _properties.PropertyChanged -= OnPropertiesChanged;   // deterministic teardown
    }

    private void OnPropertiesChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}
