// Stage 2A shape s04: an early return before the release. Truth: released on the fall-through path only (may).
using System;
sealed class R : IDisposable { public bool IsOpen => true; public void Touch() { } public void Dispose() { } }
static class S04
{
    static void Finish(R r, bool skip)
    {
        if (skip)
        {
            return;
        }
        r.Dispose();
    }
}
