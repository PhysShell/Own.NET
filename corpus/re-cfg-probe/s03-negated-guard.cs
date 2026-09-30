// Stage 2A shape s03: a negated flag guard. Truth: r is released iff !keep (Split(!keep): may off the seam).
using System;
sealed class R : IDisposable { public bool IsOpen => true; public void Touch() { } public void Dispose() { } }
static class S03
{
    static void Finish(R r, bool keep)
    {
        if (!keep)
        {
            r.Dispose();
        }
    }
}
