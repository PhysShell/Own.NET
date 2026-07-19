// BUGGY (WPF002 soundness slice; hand-reduced into case.own).
//
// The Stop() DOES sit on a teardown path (Dispose calls Shutdown), but behind
// a guard that depends on a PARAMETER of the enclosing method — the caller
// chooses whether the release runs. Same #278 rule as the parameter-guarded
// `-=`: not proven.
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
        Shutdown(false);
    }

    private void Shutdown(bool stopTimer)
    {
        if (stopTimer)
            _timer.Stop();     // caller-controlled: the release may be skipped
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
