// FIXED (synthetic conformance). The owner enrolls the subscriber in a `using`.
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
        using var sub = new Subscriber(source);
        return sub.GetHashCode();
    }
}
