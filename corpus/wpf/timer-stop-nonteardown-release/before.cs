// BUGGY (WPF002 soundness slice; hand-reduced into case.own).
//
// The ctor wires and starts a timer; the only `Stop()` sits in an arbitrary
// public method (`Pause`) that no lifecycle path is proven to call. The mere
// EXISTENCE of a Stop() is not evidence that it RUNS — the same #278 rule that
// already governs `-=`. The old "any Stop() on the receiver = released" model
// silenced this — the false negative this case pins.
//
// own-check MUST flag this OWN001 [resource: timer].
using System;

public sealed class TickerView
{
    private readonly DispatcherTimer _timer = new DispatcherTimer();

    public TickerView()
    {
        _timer.Tick += OnTick;
        _timer.Start();
    }

    public void Pause()
    {
        _timer.Stop();     // arbitrary method: nobody has to call this
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
