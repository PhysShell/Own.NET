using System;
using System.Threading;

// A "drain and dispose" sink: stops the timer, then disposes it. Because its
// receiver parameter is disposed in the body, a `_timer.WaitForDispose(...)` call
// releases the field — the extractor proves this by inspecting the sink's body
// (ConsumesParam on the reduced extension method's receiver), not by name.
static class TimerSink
{
    public static void WaitForDispose(this Timer timer, TimeSpan timeout)
    {
        timer.Change(Timeout.Infinite, Timeout.Infinite);
        timer.Dispose();
    }
}

// FIX: the owned Timer field is released through the sink on Dispose. No literal
// `_timer.Dispose()` appears, so recognising this requires following the sink's
// dispose effect — once we do, there is no leak and the case is silent.
sealed class Worker : IDisposable
{
    readonly Timer _timer;

    public Worker() => _timer = new Timer(_ => { }, null, 0, 1000);

    public void Dispose() => _timer.WaitForDispose(TimeSpan.Zero);
}
