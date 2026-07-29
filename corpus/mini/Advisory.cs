using System;

namespace Own.Corpus.Mini;

// AN ADVISORY, NOT A VERDICT. `ExternalWidget` is deliberately undeclared and
// unreferenced, so the extractor sees a `+=` that looks like an event subscription
// but cannot bind its left side to an event symbol. It does NOT guess a leak: it
// emits an `unresolved-subscription` record and the core surfaces OWN050 —
// "leakage analysis skipped" — as an advisory note, rendered as a warning and
// excluded from the exit code.
//
// It is in the frozen corpus because the advisory population is compared through
// the ledger census rather than through the findings list (normalization routes
// coverage notes out of `findings` and counts them in `coverage`). Without a note
// here, that comparison would be two empty tallies agreeing with each other.
public sealed class UnresolvedSource
{
    public UnresolvedSource()
    {
        ExternalWidget.Changed += OnChanged;
    }

    private void OnChanged(object? sender, EventArgs e) { }
}
