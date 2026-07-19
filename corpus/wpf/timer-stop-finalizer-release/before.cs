// BUGGY (WPF002 soundness slice; hand-reduced into case.own).
//
// The only `Stop()` sits in the FINALIZER. A finalizer is not a teardown
// proof: it runs only if the object is ever collected — and the running timer
// is exactly what keeps the object reachable, so the finalizer never fires
// for the live leak. Same rule as the `-=`-in-finalizer case (#278).
//
// own-check MUST flag this OWN001 [resource: timer].
using System;

public sealed class HeartbeatMonitor
{
    private readonly DispatcherTimer _timer = new DispatcherTimer();

    public HeartbeatMonitor()
    {
        _timer.Tick += OnBeat;
        _timer.Start();
    }

    ~HeartbeatMonitor()
    {
        _timer.Stop();     // never proven to run; the timer pins the object
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
