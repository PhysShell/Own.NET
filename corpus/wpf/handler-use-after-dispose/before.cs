// BUGGY (representative WPF pattern; the C# extractor now catches this end-to-end via its one-hop
// indirect field-UAF pass).
//
// The VM disposes its subscription (and its owned connection) on close, but a callback already
// queued on the dispatcher still runs after Dispose() and reaches the disposed connection
// INDIRECTLY: the handler calls a private `Refresh()` helper that reads `_conn` (disposed in
// Dispose()). In real code this surfaces as an ObjectDisposedException or a read of torn state.
// Unlike `field-use-after-dispose` (a DIRECT `_conn.X` read in the handler), here the disposed field
// is one hop down, behind the helper — the extractor chases that single hop. The fix (after.cs)
// guards the handler on a disposed flag before it calls the helper.
using System;
using System.Data.SqlClient;

public sealed class CustomerViewModel : IDisposable
{
    private readonly IDisposable _sub;
    private readonly SqlConnection _conn;

    public CustomerViewModel(IEventBus bus)
    {
        _conn = new SqlConnection("Server=.;Database=Customers");
        _sub = bus.Subscribe<CustomerChanged>(OnCustomerChanged);
    }

    private void OnCustomerChanged(CustomerChanged e)
    {
        // a late, already-dispatched callback: runs after Dispose()
        Refresh();   // reaches the disposed _conn INDIRECTLY (one hop, through the helper)
    }

    private void Refresh()
    {
        _conn.ChangeDatabase("customers");   // <-- reads the disposed connection
    }

    public void Dispose()
    {
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
