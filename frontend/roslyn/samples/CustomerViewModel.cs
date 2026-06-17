using System;

// SUBSCRIPTION LEAK (injected source): subscribes to an event bus passed into the
// constructor and never unsubscribes. The extractor emits the subscription with
// released=false and source=injected. Because `bus` is an INJECTED dependency we
// cannot prove whether it outlives this view model (it might be a singleton, or
// might not), so for now the core reports OWN001 at WARNING level — an honest
// "possible leak", not a hard error. Once Own.NET models lifetimes/ownership well
// enough to prove the source is long-lived, this escalates to an error (a static
// event, or a proven app-lifetime source, is already a hard error today).
public sealed class CustomerViewModel
{
    public CustomerViewModel(IEventBus bus)
    {
        bus.CustomerChanged += OnCustomerChanged;   // no matching -= anywhere -> leak
    }

    private void OnCustomerChanged(object? sender, EventArgs e) { }
}
