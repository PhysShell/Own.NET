// BUGGY (class 5, post-hoc control A for F4-S1, added after the owner's audit
// of c57a919). Identical to F4-S1's buggy side except for ONE variable: the
// type now implements IDisposable. The owner still constructs the cache and
// drops it, so the teardown still never runs. Lifecycle state: BUG REMAINS.
// The cell answers: which tools fire on the enrollment bug once the interface
// convention is satisfied (the RAII rules: CA2000 / IDISP001 / Owen's OWN001)?
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
        var cache = new Cache(settings);                  // nobody calls cache.Dispose()
        return cache.GetHashCode();
    }
}
