// FIXED. The callback guards on the disposed flag (and/or the subscription is
// disposed only after the dispatcher queue is drained), so nothing touches the
// subscription-backed state after Dispose().
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
        if (_disposed) return;   // do not touch disposed state
        Refresh();
    }

    private void Refresh() { /* ... */ }

    public void Dispose()
    {
        _disposed = true;
        _sub.Dispose();
    }
}
