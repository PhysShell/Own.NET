// FIXED (class 5, post-hoc control A for F4-S1; this side is F4-S1's fixed side
// verbatim: the (interface present, owner enrolls) cell of the 2x2). The type
// implements IDisposable and the owner enrolls it in a `using`, so the
// teardown provably runs.
using System;
using System.ComponentModel;

public sealed class Cache : IDisposable
{
    private readonly INotifyPropertyChanged _settings;   // injected, unknown lifetime

    public Cache(INotifyPropertyChanged settings)
    {
        _settings = settings;
        _settings.PropertyChanged += OnSettingsChanged;
    }

    public void Dispose()
    {
        _settings.PropertyChanged -= OnSettingsChanged;
    }

    private void OnSettingsChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}

public static class CacheUser
{
    public static int Use(INotifyPropertyChanged settings)
    {
        using var cache = new Cache(settings);            // enrolled: Dispose runs at scope exit
        return cache.GetHashCode();
    }
}
