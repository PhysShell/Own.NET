// BUGGY (WPF002 twin of subscription-teardown-early-return-guard: the #278
// parameter guard spelled as an early return).
//
// Dispose() calls the helper with keepTicking: true ("light" teardown), and the
// helper's Stop() sits AFTER `if (keepTicking) return;`. The release provably
// never runs on any path — an early `return` is a preceding sibling of the
// Stop(), invisible to an ancestors-only guard walk, while the symbol-based
// teardown closure credits the helper regardless of argument values.
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
        Shutdown(keepTicking: true);   // "light" teardown: the production path
    }

    private void Shutdown(bool keepTicking)
    {
        if (keepTicking)
            return;                    // every caller passes true
        _timer.Stop();                 // never reached
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
