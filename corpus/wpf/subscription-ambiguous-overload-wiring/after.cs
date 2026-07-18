// FIXED. Exactly ONE `Window_Closing` remains — the delegate-compatible one —
// and it holds the `-=`. With the lifecycle event still unresolved, the name
// is now UNAMBIGUOUS (a single same-named method in the immediate class), so
// the fallback may credit it: whichever overload the delegate would pick, it
// is this one.
//
// own-check MUST treat the subscription as released (silent); the unresolved
// `Closing +=` itself stays the usual OWN050 advisory.
using System;
using System.ComponentModel;

public partial class OrdersWindow : Window
{
    private readonly INotifyPropertyChanged _orders;   // injected, unknown lifetime

    public OrdersWindow(INotifyPropertyChanged orders)
    {
        _orders = orders;
        _orders.PropertyChanged += OnOrdersChanged;
        Closing += Window_Closing;
    }

    private void Window_Closing(object sender, CancelEventArgs e)
    {
        _orders.PropertyChanged -= OnOrdersChanged;    // the one and only candidate
    }

    private void OnOrdersChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}
