// Stage 2A shape s11: a tracked local reassigned before its release. Truth: the first R leaks (OWN001 at line 8),
// the second is released; distinguishing them needs a def-use / SSA view.
using System;
sealed class R : IDisposable { public bool IsOpen => true; public void Touch() { } public void Dispose() { } }
static class S11
{
    static void Run()
    {
        var r = new R();
        r = new R();
        r.Dispose();
    }
}
