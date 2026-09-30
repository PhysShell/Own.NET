// Stage 2A shape s07: a wrapper that forwards to an unconditional releaser. Truth: Drop consumes r (must, transitively).
using System;
sealed class R : IDisposable { public bool IsOpen => true; public void Touch() { } public void Dispose() { } }
static class S07
{
    static void Finish(R r)
    {
        r.Dispose();
    }

    static void Drop(R r)
    {
        Finish(r);
    }
}
