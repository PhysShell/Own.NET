using System;

// NOT a leak (P-004 self-owned exemption): the event source `_calc` is a field
// this class constructs and therefore OWNS — its lifetime cannot exceed the
// view-model's, so the `_calc <-> this` reference cycle is collectable by the GC
// even with no `-=`. The extractor must stay SILENT here, unlike CustomerViewModel
// where the source is an injected (longer-lived) bus. Timers are the exception
// (a running timer is dispatcher-rooted regardless of ownership) — see TimerViewModel.
public sealed class SelfOwnedViewModel
{
    private readonly Calc _calc = new();

    public SelfOwnedViewModel()
    {
        _calc.Changed += OnChanged;   // self-owned source -> not a leak, no finding
    }

    private void OnChanged(object? sender, EventArgs e) { }
}
