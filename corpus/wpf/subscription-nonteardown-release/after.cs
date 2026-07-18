// FIXED. The detach moved into a recognised lifecycle teardown: a handler the
// class wires to its OWN `Unloaded` event in the ctor. The platform raises
// `Unloaded` when the view leaves the tree, so the `-=` provably runs at the
// subscriber's end-of-life — this is the P-004 teardown shape as written
// ("no matching `-=` in Dispose/OnClosed/Unloaded" is the finding; a `-=` IN
// one of those contexts is the fix).
//
// own-check MUST treat this as released (silent) — the recognised lifecycle
// teardown keeps its existing no-finding behaviour under #278.
using System;
using System.ComponentModel;

public sealed class PriceListener
{
    private readonly INotifyPropertyChanged _prices;   // injected, unknown lifetime

    public event EventHandler Unloaded;                // raised by the host when the view is torn down

    public PriceListener(INotifyPropertyChanged prices)
    {
        _prices = prices;
        _prices.PropertyChanged += OnPricesChanged;
        Unloaded += OnViewUnloaded;
    }

    private void OnViewUnloaded(object sender, EventArgs e)
    {
        _prices.PropertyChanged -= OnPricesChanged;    // teardown context: the class's own Unloaded hook
    }

    private void OnPricesChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}
