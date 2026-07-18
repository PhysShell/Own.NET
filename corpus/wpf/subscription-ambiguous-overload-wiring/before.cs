// BUGGY (#278 follow-up 2 — the unresolved-overload fallback; hand-reduced
// into case.own).
//
// The class wires `Closing += Window_Closing` on an UNRESOLVED lifecycle event
// (the WPF `Window` base never resolves on a Linux runner without the
// reference pack) and declares TWO `Window_Closing` overloads. The runtime
// delegate attaches exactly ONE of them — chosen by the event's delegate
// signature, which is precisely the information the extractor is missing. The
// delegate-compatible overload detaches nothing; the `-=` sits in the OTHER,
// never-attached overload.
//
// own-check MUST flag the subscription OWN001: an ambiguous name (2+ same-named
// methods) may not ground the teardown, else a `-=` in the wrong overload
// silently swallows the leak. (`Window` is deliberately not defined in-file —
// the unresolved `Closing +=` itself surfaces as the usual OWN050 advisory.)
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
        // the delegate-compatible overload: detaches nothing
    }

    private void Window_Closing(object sender, EventArgs e)
    {
        _orders.PropertyChanged -= OnOrdersChanged;    // never attached at runtime
    }

    private void OnOrdersChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}
