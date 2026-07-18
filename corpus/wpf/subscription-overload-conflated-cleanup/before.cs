// BUGGY (#278 follow-up, blocker 3; hand-reduced into case.own).
//
// Dispose calls `Cleanup()` — the no-argument overload, which detaches
// nothing. The matching `-=` lives only in `Cleanup(bool)`, an overload that
// NOTHING on the teardown path calls. A name-keyed teardown closure conflates
// the two ("Dispose calls Cleanup, Cleanup has the -=") and silently credits
// the release; only symbol-resolved call targets keep the two apart.
//
// own-check MUST flag this OWN001.
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

    public void Dispose() => Cleanup();                // resolves to Cleanup(), not Cleanup(bool)

    private void Cleanup()
    {
        // releases buffers etc. — but detaches nothing
    }

    private void Cleanup(bool detachHandlers)
    {
        _report.PropertyChanged -= OnReportChanged;    // never called from any teardown
    }

    private void OnReportChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}
