using System;

// In-sample event sources so the type-aware extractor (P-014 Tier A) can resolve
// the samples' `+=` to real events without referencing WPF or any third-party
// assembly. A real WPF/DevExpress event on an *unreferenced* type would instead
// surface as an OWN050 "leakage analysis skipped" note — that is the honest Tier A
// behavior on a project whose dependencies were not passed (see P-014).

public interface IEventBus
{
    event EventHandler CustomerChanged;
    event EventHandler OrdersChanged;
}

// A small event source a view-model can construct and own (used by the self-owned
// exemption sample): subscribing to an owned field's event is not a leak.
public sealed class Calc
{
    public event EventHandler? Changed;
    public static event EventHandler? GlobalPing;
}

namespace WpfApp
{
    // A stand-in for System.Windows.Threading.DispatcherTimer (WPF is not on the
    // Tier A reference set): the same Tick / Start / Stop surface the timer sample
    // exercises, so `_timer.Tick += OnTick` binds to a real event symbol.
    public sealed class DispatcherTimer
    {
        public event EventHandler? Tick;
        public void Start() { }
        public void Stop() { }
    }
}
