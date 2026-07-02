// FIXED. The handler guards on a disposed flag BEFORE touching the connection, so a late event
// bails before reaching disposed state. The subscription shape is unchanged
// (`+= new EventHandler(OnSourceChanged)`, self-owned source, no leak); only the read is guarded,
// so the field-UAF pass sees the `if (_disposed) return;` guard precede the read and stays silent.
using System;
using System.Data.SqlClient;

public sealed class SourceView : IDisposable
{
    private readonly Publisher _source;      // self-owned -> the subscription is not a leak
    private readonly SqlConnection _conn;
    private bool _disposed;

    public SourceView()
    {
        _source = new Publisher();
        _conn = new SqlConnection("Server=.;Database=Customers");
        _source.Changed += new EventHandler(OnSourceChanged);   // explicit delegate-creation subscription
    }

    private void OnSourceChanged(object sender, EventArgs e)
    {
        if (_disposed) return;   // do not touch disposed state
        _conn.ChangeDatabase("customers");
    }

    public void Dispose()
    {
        _disposed = true;
        _conn.Dispose();
    }
}

// Minimal in-file stand-in so the reduction is self-contained.
public sealed class Publisher { public event EventHandler Changed; }
