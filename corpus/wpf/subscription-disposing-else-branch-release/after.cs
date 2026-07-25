// FIXED. The `-=` sits inside the `if (disposing)` branch — the canonical
// IDisposable pattern the #293 disposing exception was built for: the branch
// runs on every `Dispose()` call, so the release provably runs at teardown.
//
// own-check MUST treat this as released (silent): a POSITIVE use of the single
// bool parameter of `Dispose(bool)` is the one canonical guard that does not
// demote.
using System;
using System.ComponentModel;

public sealed class ReportView : IDisposable
{
    private readonly INotifyPropertyChanged _properties;   // injected, unknown lifetime

    public ReportView(INotifyPropertyChanged properties)
    {
        _properties = properties;
        _properties.PropertyChanged += new PropertyChangedEventHandler(OnPropertiesChanged);
    }

    public void Dispose()
    {
        Dispose(true);
        GC.SuppressFinalize(this);
    }

    private void Dispose(bool disposing)
    {
        if (disposing)
        {
            _properties.PropertyChanged -= OnPropertiesChanged;   // managed-dispose branch
        }
    }

    ~ReportView()
    {
        Dispose(false);
    }

    private void OnPropertiesChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}
