// Stage 2A shape s09: named, reordered arguments. Truth: Finish consumes `first` only; at the call the local r
// (bound to first by name) is released and x (bound to second) is kept — x leaks (OWN001), r does not.
using System;
sealed class R : IDisposable { public bool IsOpen => true; public void Touch() { } public void Dispose() { } }
static class S09
{
    static void Finish(R first, R second)
    {
        first.Dispose();
        second.Touch();
    }

    static void Run()
    {
        var r = new R();
        var x = new R();
        Finish(second: x, first: r);
    }
}
