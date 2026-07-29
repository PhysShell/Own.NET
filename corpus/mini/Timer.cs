using System;

namespace Own.Corpus.Mini;

// A started timer whose Tick is never detached and which is never stopped: the
// running timer keeps this component alive. OWN001 [resource: timer].
public sealed class TimerLeak
{
    private readonly DispatcherTimer _timer = new();

    public TimerLeak()
    {
        _timer.Tick += OnTick;
        _timer.Start();
    }

    private void OnTick(object? sender, EventArgs e) { }
}

// The same timer, stopped on teardown -> released -> silent.
public sealed class TimerStopped : IDisposable
{
    private readonly DispatcherTimer _timer = new();

    public TimerStopped()
    {
        _timer.Tick += OnTick;
        _timer.Start();
    }

    private void OnTick(object? sender, EventArgs e) { }

    public void Dispose()
    {
        _timer.Stop();
    }
}
