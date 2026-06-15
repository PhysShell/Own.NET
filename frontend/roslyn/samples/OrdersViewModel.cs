using System;

// OK: subscribes in the constructor and unsubscribes in Dispose. The extractor
// finds a matching -= (released=true), so the core reports nothing.
public sealed class OrdersViewModel : IDisposable
{
    private readonly IEventBus _bus;

    public OrdersViewModel(IEventBus bus)
    {
        _bus = bus;
        _bus.OrdersChanged += OnOrdersChanged;
    }

    public void Dispose()
    {
        _bus.OrdersChanged -= OnOrdersChanged;   // matching unsubscribe
    }

    private void OnOrdersChanged(object? sender, EventArgs e) { }
}
