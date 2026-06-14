// BUGGY (representative WPF pattern, hand-reduced into corpus/wpf/case.own).
//
// CustomerViewModel subscribes to a long-lived (App-lifetime) event bus in its
// constructor and never unsubscribes. The bus holds a strong reference to the
// VM's handler, so the VM stays reachable from an App-lifetime GC root for the
// whole process: the window closes, but the ViewModel never dies. A classic
// WPF "zombie ViewModel" leak.
public sealed class CustomerViewModel
{
    public CustomerViewModel(IEventBus bus)
    {
        // Subscribe hands back an IDisposable token, but it is ignored.
        bus.Subscribe<CustomerChanged>(OnCustomerChanged);
    }

    private void OnCustomerChanged(CustomerChanged e) { /* ... */ }

    // No Dispose, no unsubscribe -> the bus keeps this VM alive forever.
}
