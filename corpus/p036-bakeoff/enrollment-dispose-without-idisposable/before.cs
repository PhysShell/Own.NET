// BUGGY (synthetic conformance, P-036 LifecycleEffect vs LifecycleEnrollment;
// the audit's attack D). `Cache` has a perfect `Dispose()` that unsubscribes —
// but the type does NOT implement IDisposable, so no `using`, no DI scope and
// no owner will ever call it; the platform contract only invokes `Dispose`
// through the interface. `Use` constructs and drops the cache: the injected
// publisher keeps every instance alive. Effect proven, enrollment absent.
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
