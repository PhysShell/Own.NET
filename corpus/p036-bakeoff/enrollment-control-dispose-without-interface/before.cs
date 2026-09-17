// BUGGY (class 5, post-hoc control B for F4-S1; this side is F4-S1's buggy side
// verbatim: the (no interface, owner drops) cell of the 2x2). `Cache` has a
// perfect `Dispose()` that unsubscribes, but the type does NOT implement
// IDisposable and `Use` constructs and drops the cache, so the teardown never
// runs: the injected publisher keeps every instance alive. Effect proven,
// enrollment absent.
using System.ComponentModel;

public sealed class Cache
{
    private readonly INotifyPropertyChanged _settings;   // injected, unknown lifetime

    public Cache(INotifyPropertyChanged settings)
    {
        _settings = settings;
        _settings.PropertyChanged += OnSettingsChanged;
    }

    public void Dispose()                                 // a name, not a lifecycle
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
