// BUGGY (synthetic conformance, P-036 §Phase 2 fixture 7 — exceptional exit
// bypassing the cleanup). Dispose flushes a writer that may throw BEFORE the
// `-=`; on the throwing path the subscription is never released and the
// injected publisher keeps the document alive.
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
        _log.Flush();                                       // may throw (IOException)
        _properties.PropertyChanged -= OnPropertiesChanged; // skipped on the throwing path
    }

    private void OnPropertiesChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}
