// BUGGY (WPF002 soundness slice; hand-reduced into case.own).
//
// Two timers; Dispose stops only ONE of them. A Stop() releases exactly its
// own receiver — the sibling's Stop() must not silence the other timer.
//
// own-check MUST flag the unstopped timer OWN001 [resource: timer].
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
        _slow.Stop();      // only the slow timer; _fast keeps running
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
