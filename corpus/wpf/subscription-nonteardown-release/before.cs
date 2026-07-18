// BUGGY (issue #278, rule 3; hand-reduced into case.own).
//
// A listener subscribes to an injected publisher in its ctor. The only matching
// `-=` is UNCONDITIONAL — but it sits in an arbitrary method (`StopListening`)
// that is not a teardown: nothing here proves any owner ever calls it (in the
// real SectorTS analog, an entire subsystem constructs these objects and never
// calls the unregister method). The mere EXISTENCE of a `-=` is not evidence
// that it RUNS.
//
// own-check MUST flag this OWN001. The old "any matching `-=` in the class =
// released" model silenced it — the false negative this case pins.
using System.ComponentModel;

public sealed class PriceListener
{
    private readonly INotifyPropertyChanged _prices;   // injected, unknown lifetime

    public PriceListener(INotifyPropertyChanged prices)
    {
        _prices = prices;
        _prices.PropertyChanged += OnPricesChanged;
    }

    public void StopListening()
    {
        _prices.PropertyChanged -= OnPricesChanged;    // unconditional, but nobody has to call this
    }

    private void OnPricesChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}
