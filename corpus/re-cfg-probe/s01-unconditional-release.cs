// resource-effects Stage 2A shape s01 (pre-registered in Own.NET-paperwork stage2a-cfg-probe-prereg-v1.json):
// an unconditional release of the parameter. Truth: Finish consumes r (must).
using System;
sealed class R : IDisposable { public bool IsOpen => true; public void Touch() { } public void Dispose() { } }
static class S01
{
    static void Finish(R r)
    {
        r.Dispose();
    }
}
