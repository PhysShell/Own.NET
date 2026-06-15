using System;

// LEAK: subscribes to a (longer-lived) event bus in its constructor and never
// unsubscribes. The extractor emits a subscription with released=false, and the
// core reports OWN001 at the `+=` line.
public sealed class CustomerViewModel
{
    public CustomerViewModel(IEventBus bus)
    {
        bus.CustomerChanged += OnCustomerChanged;   // no matching -= anywhere -> leak
    }

    private void OnCustomerChanged(object? sender, EventArgs e) { }
}
