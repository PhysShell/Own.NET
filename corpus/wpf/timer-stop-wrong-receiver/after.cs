// FIXED. Dispose stops BOTH timers — each receiver released by its own
// Stop() in the teardown.
using System;

public sealed class DualPoller : IDisposable
{
    private readonly DispatcherTimer _fast = new DispatcherTimer();
    private readonly DispatcherTimer _slow = new DispatcherTimer();

    public DualPoller()
    {
        _fast.Tick += OnFast;
        _fast.Start();
        _slow.Tick += OnSlow;
        _slow.Start();
    }

    public void Dispose()
    {
        _fast.Stop();
        _slow.Stop();
    }

    private void OnFast(object sender, EventArgs e) { /* ... */ }
    private void OnSlow(object sender, EventArgs e) { /* ... */ }
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
