// FIXED. The one subscription the ctor creates is released UNCONDITIONALLY in
// Dispose — a recognised teardown context with no caller-controlled guard, so
// the release provably runs when the owner is torn down.
//
// own-check MUST treat this as released (silent): the `-=` is in `Dispose`,
// matches the `+=`'s (receiver, handler) pair (the explicit delegate-creation
// on the `+=` normalizes to the bare method group on the `-=`), and no
// parameter of the enclosing method can skip it.
using System;
using System.ComponentModel;

public sealed class GoodsDocument : IDisposable
{
    private readonly INotifyPropertyChanged _properties;   // injected, unknown lifetime

    public GoodsDocument(INotifyPropertyChanged properties)
    {
        _properties = properties;
        _properties.PropertyChanged += new PropertyChangedEventHandler(OnPropertiesChanged);
    }

    public void Dispose()
    {
        _properties.PropertyChanged -= OnPropertiesChanged;   // unconditional, in a teardown
    }

    private void OnPropertiesChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}
