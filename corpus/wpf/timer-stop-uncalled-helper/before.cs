// BUGGY (WPF002 soundness slice; hand-reduced into case.own).
//
// The Stop() sits in a private helper (`ReleaseTimer`) that NO teardown ever
// calls — only an arbitrary public method does. Declaration is not execution;
// a helper joins the teardown closure only when a teardown provably CALLS it
// (the symbol-resolved transitive rule from #278).
//
// own-check MUST flag this OWN001 [resource: timer].
using System;

public sealed class ChartRefresher
{
    private readonly DispatcherTimer _timer = new DispatcherTimer();

    public ChartRefresher()
    {
        _timer.Tick += OnRefresh;
        _timer.Start();
    }

    public void Reset()
    {
        ReleaseTimer();    // arbitrary method: nobody has to call this
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
