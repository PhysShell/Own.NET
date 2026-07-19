// FIXED. The SAME lambda body — but now it is the handler wired to the pane's
// own Closed lifecycle event, so it provably runs at teardown.
using System;

public sealed class PollingPane
{
    private readonly DispatcherTimer _timer = new DispatcherTimer();

    public event EventHandler Closed;       // raised by the host at teardown

    public PollingPane()
    {
        _timer.Tick += OnPoll;
        _timer.Start();
        this.Closed += (s, e) => _timer.Stop();   // wired lifecycle lambda
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
