// Stage 2A shape s14: a call that may throw precedes the release. Truth: must on every NORMAL exit; on the
// exceptional path r is not released (Own.NET models that with an exceptional-leak edge for locals, not as `may`).
using System;
sealed class R : IDisposable { public bool IsOpen => true; public void Touch() { } public void Dispose() { } }
static class S14
{
    static void Finish(R r)
    {
        r.Touch();
        r.Dispose();
    }
}
