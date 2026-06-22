// FIXED. The handler guards on the disposed flag, so a late dispatcher callback
// bails before touching the connection. (Equivalently, drain the dispatcher queue
// before disposing.) Nothing reads the connection after Dispose(), so the
// extractor's field-mediated use-after-dispose detector — which excludes a handler
// that opens with a `if (_disposed) return;` guard — stays silent.
using System;
using System.Data.SqlClient;

public sealed class ReportViewModel : IDisposable
{
    private readonly SqlConnection _conn;
    private readonly IDisposable _sub;
    private bool _disposed;

    public ReportViewModel(IEventBus bus)
    {
        _conn = new SqlConnection("Server=.;Database=Reports");
        _sub = bus.Subscribe(OnDataChanged);
    }

    private void OnDataChanged(DataChanged e)
    {
        if (_disposed) return;   // do not touch disposed state
        _conn.ChangeDatabase(e.Database);
    }

    public void Dispose()
    {
        _disposed = true;
        _sub.Dispose();
        _conn.Dispose();
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
