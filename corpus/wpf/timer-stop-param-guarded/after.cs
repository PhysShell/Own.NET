// FIXED. The SAME teardown path — but the guard is now the class's OWN state
// (a field), not a caller-controlled parameter, so the release is credited
// (field guards are the class's own bookkeeping).
using System;

public sealed class FeedTicker : IDisposable
{
    private readonly DispatcherTimer _timer = new DispatcherTimer();
    private bool _running;

    public FeedTicker()
    {
        _timer.Tick += OnTick;
        _timer.Start();
        _running = true;
    }

    public void Dispose()
    {
        Shutdown();
    }

    private void Shutdown()
    {
        if (_running)
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
