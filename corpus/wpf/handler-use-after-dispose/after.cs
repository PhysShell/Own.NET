// FIXED. The callback guards on the disposed flag BEFORE it calls the helper, so a late, already-
// dispatched callback bails before anything reaches the connection. (Equivalently, drain the
// dispatcher queue before disposing.) The extractor's field-UAF pass sees the opening
// `if (_disposed) return;` guard precede the helper call and stays silent.
using System;
using System.Data.SqlClient;

public sealed class CustomerViewModel : IDisposable
{
    private readonly IDisposable _sub;
    private readonly SqlConnection _conn;
    private bool _disposed;

    public CustomerViewModel(IEventBus bus)
    {
        _conn = new SqlConnection("Server=.;Database=Customers");
        _sub = bus.Subscribe<CustomerChanged>(OnCustomerChanged);
    }

    private void OnCustomerChanged(CustomerChanged e)
    {
        if (_disposed) return;   // do not touch disposed state
        Refresh();
    }

    private void Refresh()
    {
        _conn.ChangeDatabase("customers");
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
    IDisposable Subscribe<T>(Action<T> handler);
}

public sealed class CustomerChanged { }
