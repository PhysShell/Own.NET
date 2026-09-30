// Stage 2A shape s02: a flag-guarded release. Truth: r is released iff b (Split(b): may off the seam).
using System;
sealed class R : IDisposable { public bool IsOpen => true; public void Touch() { } public void Dispose() { } }
static class S02
{
    static void Finish(R r, bool b)
    {
        if (b)
        {
            r.Dispose();
        }
    }
}
