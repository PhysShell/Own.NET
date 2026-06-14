// BUGGY (representative WPF pattern, hand-reduced into case.own).
//
// A Window-scoped ViewModel subscribes itself to an App-scoped (singleton) event
// bus with a strong handler and keeps no unsubscribe token. The bus is reachable
// from an App-lifetime GC root, and through the strong delegate so is the VM:
// the VM is *promoted* to App lifetime. Close the window all you want -- the VM
// lives until the process exits. The lifetime mismatch (VM expected Window,
// actually App) is the leak.
public sealed class CustomerViewModel
{
    public CustomerViewModel(IEventBus appBus)   // appBus: App lifetime (singleton)
    {
        // strong subscription, no token kept -> VM promoted to App lifetime
        appBus.CustomerChanged += OnCustomerChanged;
    }

    private void OnCustomerChanged(object? sender, EventArgs e) { /* ... */ }
}
