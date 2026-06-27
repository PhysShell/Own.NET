using System;
using System.Threading;

// The "detach and dispose" teardown: stop + dispose the timer through the sink.
static class TimerSink
{
    public static void WaitForDispose(this Timer timer, TimeSpan timeout)
    {
        timer.Change(Timeout.Infinite, Timeout.Infinite);
        timer.Dispose();
    }
}

// FIX: the owned Timer field is released through the canonical atomic teardown —
// `Interlocked.Exchange(ref _timer, null)` hands back the live timer and nulls the
// field, then the sink disposes it. Recognising this needs two hops: the local
// `current` is bound to `_timer` because Exchange returns the field's owned object
// (RefExchangeNulledField), and `current?.WaitForDispose(...)` is a release because
// the sink disposes its receiver (CallReleasesReceiver). Together → no leak, silent.
sealed class Continuation : IDisposable
{
    Timer? _timer;

    public Continuation() => _timer = new Timer(_ => { }, null, 0, 1000);

    public void Dispose() => StopTimer();

    void StopTimer()
    {
        var current = Interlocked.Exchange(ref _timer, null);
        current?.WaitForDispose(TimeSpan.Zero);
    }
}
