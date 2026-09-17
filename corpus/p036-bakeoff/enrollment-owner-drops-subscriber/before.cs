// BUGGY (synthetic conformance, P-036 LifecycleEnrollment — the RAII form).
// The subscriber is a correct IDisposable: it unsubscribes in Dispose. The
// OWNER is the bug: it constructs the subscriber and drops it, so Dispose never
// runs and the injected publisher keeps the subscriber alive. Existing
// Dispose/RAII checkers cover this half (an undisposed IDisposable local).
using System;
using System.ComponentModel;

public sealed class Subscriber : IDisposable
{
    private readonly INotifyPropertyChanged _source;

    public Subscriber(INotifyPropertyChanged source)
    {
        _source = source;
        _source.PropertyChanged += OnChanged;
    }

    public void Dispose()
    {
        _source.PropertyChanged -= OnChanged;
    }

    private void OnChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}

public static class Owner
{
    public static int Run(INotifyPropertyChanged source)
    {
        var sub = new Subscriber(source);                 // never disposed -> leak
        return sub.GetHashCode();
    }
}
