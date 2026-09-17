// FIXED (synthetic conformance). The `-=` runs in a `finally`, so every exit of
// Dispose — normal or exceptional — releases the subscription.
using System;
using System.ComponentModel;
using System.IO;

public sealed class Document : IDisposable
{
    private readonly INotifyPropertyChanged _properties;   // injected, unknown lifetime
    private readonly TextWriter _log;

    public Document(INotifyPropertyChanged properties, TextWriter log)
    {
        _properties = properties;
        _log = log;
        _properties.PropertyChanged += OnPropertiesChanged;
    }

    public void Dispose()
    {
        try
        {
            _log.Flush();
        }
        finally
        {
            _properties.PropertyChanged -= OnPropertiesChanged;
        }
    }

    private void OnPropertiesChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}
