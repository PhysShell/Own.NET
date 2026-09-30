// Stage 2A shape s06: two exits, one releases. Truth: may (the fall-through exit keeps r).
using System;
sealed class R : IDisposable { public bool IsOpen => true; public void Touch() { } public void Dispose() { } }
static class S06
{
    static void Finish(R r, bool b)
    {
        if (b)
        {
            r.Dispose();
            return;
        }
        r.Touch();
    }
}
