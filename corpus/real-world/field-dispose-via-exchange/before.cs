using System;
using System.Threading;

// The "detach and dispose" teardown mined on NLog's TimeoutContinuation: the owned
// Timer field is meant to be released via `Interlocked.Exchange(ref _timer, null)`
// (which hands back the live timer and nulls the field) followed by the
// `WaitForDispose(this Timer)` sink. Here the teardown is missing entirely.
static class TimerSink
{
    public static void WaitForDispose(this Timer timer, TimeSpan timeout)
    {
        timer.Change(Timeout.Infinite, Timeout.Infinite);
        timer.Dispose();
    }
}

// BUG: the owned Timer field is constructed and never released on any path → OWN001.
sealed class Continuation : IDisposable
{
    Timer? _timer;

    public Continuation() => _timer = new Timer(_ => { }, null, 0, 1000);

    public void Dispose()
    {
        // nothing — _timer is leaked
    }
}
