// FIXED. The subscription is kept as a disposable token and released when the
// VM is disposed (on window close), so the App-lived bus no longer holds the
// Window-lived VM: the VM drops back to its intended Window lifetime and is
// collectable. (In OwnLang terms this is the slice-#1 acquire/release token
// pattern; the region check then sees a release path and stays quiet.)
public sealed class CustomerViewModel : IDisposable
{
    private readonly IDisposable _customerChanged;

    public CustomerViewModel(IEventBus appBus)
    {
        _customerChanged = appBus.Subscribe<CustomerChanged>(OnCustomerChanged);
    }

    private void OnCustomerChanged(CustomerChanged e) { /* ... */ }

    public void Dispose()
    {
        _customerChanged.Dispose();   // release path -> VM no longer promoted
    }
}
