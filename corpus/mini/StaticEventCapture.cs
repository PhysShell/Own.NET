using System;

namespace Own.Corpus.Mini;

// A REGION ESCAPE, not a token leak: an INSTANCE handler on a process-lived STATIC
// event. The extractor lowers the static-source `+=` to a `capture` fact and the
// core's lifetime engine reports OWN014 — this component is promoted to process
// lifetime and can never be collected. A different rule and a different message
// than OWN001, so it is a distinct pattern in the corpus projection.
public sealed class StaticEventEscape
{
    private int _state;

    public StaticEventEscape()
    {
        Calc.GlobalPing += OnPing;
    }

    private void OnPing(object? sender, EventArgs e) { _state++; }
}

// The same static subscription, detached on teardown -> released capture -> silent.
public sealed class StaticEventReleased : IDisposable
{
    private int _state;

    public StaticEventReleased()
    {
        Calc.GlobalPing += OnPing;
    }

    private void OnPing(object? sender, EventArgs e) { _state++; }

    public void Dispose()
    {
        Calc.GlobalPing -= OnPing;
    }
}
