// FIXED. The flag is gone: Dispose() -> Shutdown() and the helper stops the
// timer unconditionally on the resolved teardown path.
using System;

public sealed class FeedTicker : IDisposable
{
    private readonly DispatcherTimer _timer = new DispatcherTimer();

    public FeedTicker()
    {
        _timer.Tick += OnTick;
        _timer.Start();
    }

    public void Dispose()
    {
        Shutdown();
    }

    private void Shutdown()
    {
        _timer.Stop();                 // unconditional, on the teardown path
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
