// Stage 2A shape s05: the release in a finally block. Truth: released on every path (must).
using System;
sealed class R : IDisposable { public bool IsOpen => true; public void Touch() { } public void Dispose() { } }
static class S05
{
    static void Finish(R r)
    {
        try
        {
            r.Touch();
        }
        finally
        {
            r.Dispose();
        }
    }
}
