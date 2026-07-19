// FIXED. The SAME Stop() — but now it runs in Dispose, a proven teardown
// context, unconditionally. own-check MUST treat the timer as released
// (silent).
using System;

public sealed class TickerView : IDisposable
{
    private readonly DispatcherTimer _timer = new DispatcherTimer();

    public TickerView()
    {
        _timer.Tick += OnTick;
        _timer.Start();
    }

    public void Dispose()
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
