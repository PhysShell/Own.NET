using System;

namespace WpfApp;

// A DispatcherTimer (the in-sample stand-in from SampleTypes.cs — WPF is not on
// the Tier A reference set) whose Tick handler is never detached and the timer is
// never stopped: the running timer keeps this view-model alive. The core reports
// OWN001 [resource: timer] at the `+=` line.
public sealed class TimerViewModel
{
    private readonly DispatcherTimer _timer = new();

    public TimerViewModel()
    {
        _timer.Tick += OnTick;   // acquire (timer) — never stopped/detached => leak
        _timer.Start();
    }

    private void OnTick(object? sender, EventArgs e) { }
}

// The same timer, stopped on teardown — released, so the core stays silent.
public sealed class CleanTimerViewModel : IDisposable
{
    private readonly DispatcherTimer _timer = new();

    public CleanTimerViewModel()
    {
        _timer.Tick += OnTick;
        _timer.Start();
    }

    private void OnTick(object? sender, EventArgs e) { }

    public void Dispose()
    {
        _timer.Stop();   // release via Stop()
    }
}
