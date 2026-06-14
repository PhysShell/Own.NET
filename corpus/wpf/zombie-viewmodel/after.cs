// FIXED. The VM stores the subscription token and disposes it, so when the VM
// is itself disposed (e.g. on window close) it drops out of the bus's reference
// set and becomes collectable.
public sealed class CustomerViewModel : IDisposable
{
    private readonly IDisposable _customerChanged;

    public CustomerViewModel(IEventBus bus)
    {
        _customerChanged = bus.Subscribe<CustomerChanged>(OnCustomerChanged);
    }

    private void OnCustomerChanged(CustomerChanged e) { /* ... */ }

    public void Dispose()
    {
        _customerChanged.Dispose();   // unsubscribe -> VM no longer reachable
    }
}
