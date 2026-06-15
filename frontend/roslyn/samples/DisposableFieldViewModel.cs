using System;
using System.Threading;

namespace WpfApp;

// A CancellationTokenSource the view-model creates but never disposes: the owner
// leaks it. The core reports OWN001 [resource: disposable field] at the field.
public sealed class ReportViewModel
{
    private readonly CancellationTokenSource _cts = new();

    public void Refresh()
    {
        _cts.Cancel();   // used, but never disposed => leak
    }
}

// The same field, disposed on teardown — released, so the core stays silent.
public sealed class CleanReportViewModel : IDisposable
{
    private readonly CancellationTokenSource _cts = new();

    public void Refresh()
    {
        _cts.Cancel();
    }

    public void Dispose()
    {
        _cts.Dispose();   // release
    }
}
