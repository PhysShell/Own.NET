// Stage 2A shape s13: a release behind an opaque predicate. Truth: may (the predicate is not a stable flag).
using System;
sealed class R : IDisposable { public bool IsOpen => true; public void Touch() { } public void Dispose() { } }
static class S13
{
    static void Finish(R r)
    {
        if (r.IsOpen)
        {
            r.Dispose();
        }
    }
}
