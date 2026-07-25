// FIXED. The flag is gone: Dispose() -> Cleanup() and the helper releases
// unconditionally. The symbol-based teardown closure resolves the call and
// credits exactly this helper (the same proven shape as
// subscription-overload-conflated-cleanup/after.cs).
//
// own-check MUST treat this as released (silent): the `-=` is on the resolved
// teardown path, matches the `+=`'s (receiver, handler) pair, and no parameter
// of the enclosing method can skip it.
using System;
using System.ComponentModel;

public sealed class SessionDocument : IDisposable
{
    private readonly INotifyPropertyChanged _properties;   // injected, unknown lifetime

    public SessionDocument(INotifyPropertyChanged properties)
    {
        _properties = properties;
        _properties.PropertyChanged += new PropertyChangedEventHandler(OnPropertiesChanged);
    }

    public void Dispose() => Cleanup();

    private void Cleanup()
    {
        _properties.PropertyChanged -= OnPropertiesChanged;   // unconditional, on the teardown path
    }

    private void OnPropertiesChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}
