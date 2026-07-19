// FIXED. The SAME handler name — but now the ctor provably wires it to the
// view's own Closing lifecycle event, so the Stop() inside it runs at
// teardown. The release is credited by the wiring, never by the name.
using System;

public sealed class SplashTicker
{
    private readonly DispatcherTimer _timer = new DispatcherTimer();

    public event EventHandler Closing;      // raised by the host at teardown

    public SplashTicker()
    {
        _timer.Tick += OnTick;
        _timer.Start();
        this.Closing += Window_Closing;     // the wiring is the proof
    }

    private void Window_Closing(object sender, EventArgs e)
    {
        _timer.Stop();
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
