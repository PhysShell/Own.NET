// FIXED. The Stop() moves to a recognised platform teardown method
// (`OnClosed`) — a real teardown root, so the release is proven.
using System;

public class HeartbeatMonitor
{
    private readonly DispatcherTimer _timer = new DispatcherTimer();

    public HeartbeatMonitor()
    {
        _timer.Tick += OnBeat;
        _timer.Start();
    }

    protected virtual void OnClosed(EventArgs e)
    {
        _timer.Stop();
    }

    private void OnBeat(object sender, EventArgs e) { /* ... */ }
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
