// FIXED. The overload Dispose actually calls now holds the `-=`; the
// symbol-based teardown closure resolves `Dispose() -> Cleanup()` and credits
// exactly that overload.
//
// own-check MUST treat this as released (silent).
using System;
using System.ComponentModel;

public sealed class ReportView : IDisposable
{
    private readonly INotifyPropertyChanged _report;   // injected, unknown lifetime

    public ReportView(INotifyPropertyChanged report)
    {
        _report = report;
        _report.PropertyChanged += OnReportChanged;
    }

    public void Dispose() => Cleanup();

    private void Cleanup()
    {
        _report.PropertyChanged -= OnReportChanged;    // on the resolved teardown path
    }

    private void Cleanup(bool detachHandlers)
    {
        // the uncalled overload no longer carries the only release
    }

    private void OnReportChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}
