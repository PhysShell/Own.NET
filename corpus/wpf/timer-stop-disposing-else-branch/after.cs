// FIXED. The Stop() sits inside the `if (disposing)` branch — the canonical
// IDisposable pattern: the branch runs on every `Dispose()` call, so the
// release provably runs at teardown.
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
        Dispose(true);
        GC.SuppressFinalize(this);
    }

    private void Dispose(bool disposing)
    {
        if (disposing)
        {
            _timer.Stop();             // managed-dispose branch
        }
    }

    ~FeedTicker()
    {
        Dispose(false);
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
