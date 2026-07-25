// BUGGY (WPF002 twin of subscription-disposing-else-branch-release: the
// canonical Dispose(bool) pattern with the Stop() in the WRONG branch).
//
// The Stop() sits in the ELSE of `if (disposing)` — it runs only via
// `~FeedTicker() -> Dispose(false)`, and the finalizer never runs while the
// running timer keeps the owner alive. The canonical-disposing exemption
// classifies only the parameter's use in the condition (positive), never which
// branch holds the release site, so the Stop() is credited and the leak is
// silently swallowed.
//
// own-check MUST flag this OWN001 [resource: timer].
using System;

public sealed class FeedTicker : IDisposable
{
    private readonly DispatcherTimer _timer = new DispatcherTimer();

    public FeedTicker()
    {
        _timer.Tick += OnTick;
        _timer.Start();
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
            // managed cleanup of other state; the Stop() was misplaced below
        }
        else
        {
            _timer.Stop();             // finalizer-only branch
        }
    }

    ~FeedTicker()
    {
        Dispose(false);
    }

    private void OnTick(object sender, EventArgs e) { /* ... */ }
}

// In-file stand-in for System.Windows.Threading.DispatcherTimer (WPF is not on
// the corpus reference set; same shape as samples/SampleTypes.cs). NOT
// IDisposable — Stop() IS the release, which is exactly the WPF002 pattern.
public sealed class DispatcherTimer
{
    public event EventHandler Tick;
    public void Start() { }
    public void Stop() { }
}
