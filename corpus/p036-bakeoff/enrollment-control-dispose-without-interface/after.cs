// FIXED for the lifecycle (class 5, post-hoc control B for F4-S1). Identical to
// F4-S1's buggy side except for ONE variable: the owner now calls
// cache.Dispose() explicitly. The type still does NOT implement IDisposable.
// The subscription is released on the normal path (the exceptional path is
// F5's business, not this cell's). The cell answers: does IDISP009 "Add
// IDisposable interface" still fire when the lifecycle itself is fixed?
using System.ComponentModel;

public sealed class Cache
{
    private readonly INotifyPropertyChanged _settings;   // injected, unknown lifetime

    public Cache(INotifyPropertyChanged settings)
    {
        _settings = settings;
        _settings.PropertyChanged += OnSettingsChanged;
    }

    public void Dispose()                                 // still a plain method
    {
        _settings.PropertyChanged -= OnSettingsChanged;
    }

    private void OnSettingsChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}

public static class CacheUser
{
    public static int Use(INotifyPropertyChanged settings)
    {
        var cache = new Cache(settings);
        var hash = cache.GetHashCode();
        cache.Dispose();                                  // explicit teardown, no interface
        return hash;
    }
}
