using System;

// A region escape (P-004 WPF005): an INSTANCE-method handler subscribed to a
// process-lived STATIC event (Calc.GlobalPing) with no matching `-=`. The static
// event pins the handler's owner (this instance) for the whole life of the
// process, so the short-lived view-model is *promoted* to process lifetime and can
// never be collected. The extractor lowers a static-source `+=` to a `capture`
// fact, and the core's region engine reports OWN014 (the lifetime-promotion leak)
// rather than the token-model OWN001.
//
// Contrast StaticHandlerViewModel (same static event, but a STATIC handler -> null
// delegate target -> no instance retained -> silent): the deciding factor is the
// handler, not the source. Calc.GlobalPing is the self-contained analog of
// Microsoft.Win32.SystemEvents.* — a static, process-lifetime event source the
// .NET docs explicitly warn about.
public sealed class StaticEventEscapeViewModel
{
    private int _count;

    public StaticEventEscapeViewModel()
    {
        // instance handler on a process-lived static event, no `-=` kept
        // -> this view-model escapes to process lifetime (OWN014)
        Calc.GlobalPing += OnGlobalPing;
    }

    private void OnGlobalPing(object? sender, EventArgs e) { _count++; }
}

// FIXED: the instance subscription is torn down with a matching `-=` (here in
// Dispose, e.g. called on window close), so the static event no longer pins this
// instance -> no escape. The extractor's `capture` fact carries `released: true`
// and the bridge stays silent (a mitigated capture, exactly like a released token
// subscription). Must NOT be reported.
public sealed class CleanStaticEventViewModel : IDisposable
{
    private int _count;

    public CleanStaticEventViewModel()
    {
        Calc.GlobalPing += OnGlobalPing;
    }

    public void Dispose()
    {
        Calc.GlobalPing -= OnGlobalPing;   // release path -> no promotion
    }

    private void OnGlobalPing(object? sender, EventArgs e) { _count++; }
}
