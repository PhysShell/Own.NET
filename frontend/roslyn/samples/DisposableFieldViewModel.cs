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

// A `static` IDisposable field has process lifetime — it is intentionally never
// disposed (a shared HttpClient, or a sentinel like Dapper's DisposedReader.Instance,
// a false positive found by mining). The detector must NOT flag it -> silent.
public sealed class SharedTokenHolder
{
    public static readonly CancellationTokenSource Shared = new();
}
