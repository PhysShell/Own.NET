// BUGGY (representative WPF/MVVM pattern; the C# extractor now catches this
// directly under --flow-locals).
//
// A ViewModel OWNS a SqlConnection field and subscribes a handler to an injected
// event bus. On teardown Dispose() disposes the connection (and the subscription
// token), but a callback that was ALREADY queued on the dispatcher can still run
// after Dispose() and DIRECTLY touch the disposed connection
// (`_conn.ChangeDatabase(...)` on a connection already returned to the pool): an
// ObjectDisposedException / use-after-dispose.
//
// Unlike handler-use-after-dispose — whose handler reaches the disposed state
// INDIRECTLY through a `Refresh()` helper, which the extractor cannot follow — this
// handler reads the disposed FIELD directly, so the extractor's field-mediated
// cross-method detector lowers it to a synthetic acquire/release/use flow and the
// core reports OWN002. The fix (after.cs) guards the handler on the disposed flag.
using System;
using System.Data.SqlClient;

public sealed class ReportViewModel : IDisposable
{
    private readonly SqlConnection _conn;
    private readonly IDisposable _sub;

    public ReportViewModel(IEventBus bus)
    {
        _conn = new SqlConnection("Server=.;Database=Reports");
        _sub = bus.Subscribe(OnDataChanged);   // token captured + disposed below
    }

    private void OnDataChanged(DataChanged e)
    {
        // a late, already-dispatched callback: may run AFTER Dispose()
        _conn.ChangeDatabase(e.Database);   // <-- BUG: _conn may already be disposed
    }

    public void Dispose()
    {
        _sub.Dispose();    // unsubscribe
        _conn.Dispose();   // dispose the owned connection
    }
}

// Minimal in-file stand-ins so the reduction is self-contained.
public interface IEventBus
{
    IDisposable Subscribe(Action<DataChanged> handler);
}

public sealed class DataChanged
{
    public string Database { get; set; } = "";
}
