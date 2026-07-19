// BUGGY (WPF002 soundness slice; hand-reduced into case.own).
//
// The Stop() sits inside a lambda stored in a field — a deferred delegate
// nothing here proves is ever invoked. A lambda counts as teardown ONLY as
// the handler wired to a self lifecycle event (#278 rule).
//
// own-check MUST flag this OWN001 [resource: timer].
using System;

public sealed class PollingPane
{
    private readonly DispatcherTimer _timer = new DispatcherTimer();
    private readonly Action _cleanup;

    public PollingPane()
    {
        _timer.Tick += OnPoll;
        _timer.Start();
        _cleanup = () => _timer.Stop();   // declared, never proven invoked
    }

    private void OnPoll(object sender, EventArgs e) { /* ... */ }
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
