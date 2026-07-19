// FIXED. The SAME helper — but now Dispose calls it, so the helper joins the
// teardown closure (symbol-resolved, transitive) and the Stop() inside it is
// proven to run at teardown.
using System;

public sealed class ChartRefresher : IDisposable
{
    private readonly DispatcherTimer _timer = new DispatcherTimer();

    public ChartRefresher()
    {
        _timer.Tick += OnRefresh;
        _timer.Start();
    }

    public void Dispose()
    {
        ReleaseTimer();    // the teardown call is the proof
    }

    private void ReleaseTimer()
    {
        _timer.Stop();
    }

    private void OnRefresh(object sender, EventArgs e) { /* ... */ }
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
