using System;

namespace Own.Corpus.Mini;

// THE BASELINE SHAPE: `event +=` with no matching `-=`. The source is an INJECTED
// dependency of unknown lifetime, so the core reports OWN001 at WARNING level (the
// honest "possible leak"). One finding, one line, one column.
public sealed class SubscriptionLeak
{
    public SubscriptionLeak(IEventBus bus)
    {
        bus.CustomerChanged += OnCustomerChanged;
    }

    private void OnCustomerChanged(object? sender, EventArgs e) { }
}

// The same subscription, detached on teardown: released, so the core stays silent.
// A NEGATIVE control belongs in a frozen corpus for the same reason a positive one
// does — a producer change that starts flagging this would otherwise read as a
// "new_pattern" with no clue that a whole exemption broke.
public sealed class SubscriptionReleased : IDisposable
{
    private readonly IEventBus _bus;

    public SubscriptionReleased(IEventBus bus)
    {
        _bus = bus;
        _bus.OrdersChanged += OnOrdersChanged;
    }

    private void OnOrdersChanged(object? sender, EventArgs e) { }

    public void Dispose()
    {
        _bus.OrdersChanged -= OnOrdersChanged;
    }
}
