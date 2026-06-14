// BUGGY (representative WPF pattern, hand-reduced into case.own).
//
// The VM disposes its subscription on close, but a callback that was already
// queued on the dispatcher still runs and touches the (now disposed) state. In
// real code this surfaces as an ObjectDisposedException or a read of torn state.
public sealed class CustomerViewModel : IDisposable
{
    private readonly IDisposable _sub;
    private bool _disposed;

    public CustomerViewModel(IEventBus bus)
    {
        _sub = bus.Subscribe<CustomerChanged>(OnCustomerChanged);
    }

    private void OnCustomerChanged(CustomerChanged e)
    {
        // a late, already-dispatched callback: runs after Dispose()
        Refresh();   // touches subscription-backed state after it was disposed
    }

    private void Refresh() { /* reads disposed state */ }

    public void Dispose()
    {
        _disposed = true;
        _sub.Dispose();
    }
}
