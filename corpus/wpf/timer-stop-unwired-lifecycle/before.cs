// BUGGY (WPF002 soundness slice; hand-reduced into case.own).
//
// The Stop() sits in a method NAMED like a XAML-wired lifecycle handler
// (`Window_Closing`) — but nothing in code attaches it to any event. The name
// alone proves nothing (same as the `-=` twin: the suffix-only exemption was
// removed in #278's follow-up).
//
// own-check MUST flag this OWN001 [resource: timer].
using System;

public sealed class SplashTicker
{
    private readonly DispatcherTimer _timer = new DispatcherTimer();

    public SplashTicker()
    {
        _timer.Tick += OnTick;
        _timer.Start();
    }

    private void Window_Closing(object sender, EventArgs e)
    {
        _timer.Stop();     // nothing wires this handler
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
