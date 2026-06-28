using System;
using System.Threading;

// A "drain and dispose" sink: the canonical shape mined on NLog, where a Timer
// field is released not by a literal `_timer.Dispose()` but by a custom extension
// method that stops the timer and then disposes it (NLog's
// `WaitForDispose(this Timer, TimeSpan)` in Common/AsyncHelpers.cs).
static class TimerSink
{
    public static void WaitForDispose(this Timer timer, TimeSpan timeout)
    {
        timer.Change(Timeout.Infinite, Timeout.Infinite);
        timer.Dispose();
    }
}

// BUG: the owned Timer field is constructed but never released on any path —
// neither a literal `.Dispose()` nor the sink. A genuine OWN001 owned-field leak.
sealed class Worker : IDisposable
{
    readonly Timer _timer;

    public Worker() => _timer = new Timer(_ => { }, null, 0, 1000);

    public void Dispose()
    {
        // nothing — _timer is leaked
    }
}
