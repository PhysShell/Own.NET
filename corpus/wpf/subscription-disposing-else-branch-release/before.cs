// BUGGY (the canonical Dispose(bool) pattern with the `-=` in the WRONG branch).
//
// The `-=` sits in the ELSE of `if (disposing)` — the finalizer-only branch.
// The extractor's canonical-disposing exception checks only how the PARAMETER
// IDENTIFIER is used in the condition (positive, not negated), never WHICH
// branch the release site sits in — so this `-=` is credited as an unguarded
// teardown release. But the else branch runs only via `~ReportView()` ->
// `Dispose(false)`, and by the extractor's own finalizer doctrine (#278
// follow-up 1) a live subscription keeps the subscriber REACHABLE through the
// publisher's delegate — the finalizer never runs while the subscription is
// live. The release is unreachable; the leak is silently swallowed.
//
// own-check MUST flag this OWN001 (today it stays silent — the FN this pins).
using System;
using System.ComponentModel;

public sealed class ReportView : IDisposable
{
    private readonly INotifyPropertyChanged _properties;   // injected, unknown lifetime

    public ReportView(INotifyPropertyChanged properties)
    {
        _properties = properties;
        _properties.PropertyChanged += new PropertyChangedEventHandler(OnPropertiesChanged);
    }

    public void Dispose()
    {
        Dispose(true);
        GC.SuppressFinalize(this);
    }

    private void Dispose(bool disposing)
    {
        if (disposing)
        {
            // managed cleanup of other state; the unsubscribe was misplaced below
        }
        else
        {
            _properties.PropertyChanged -= OnPropertiesChanged;   // finalizer-only branch
        }
    }

    ~ReportView()
    {
        Dispose(false);
    }

    private void OnPropertiesChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}
