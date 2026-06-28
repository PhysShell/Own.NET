using System;

sealed class Res : IDisposable
{
    public void Work() { }
    public void Dispose() { }
}

static class Demo
{
    // FIX: the pre-acquired local is wrapped in the statement form `using (r) { ... }`,
    // which disposes it at every scope exit. The extractor threads that scope-exit
    // release onto the tracked local; once it does there is no leak and the case is
    // silent. (The `using (var x = ...)` declaration form never needed this — that `x`
    // is auto-disposed and is not tracked as a leak candidate; the gap was only the
    // `using (existingLocal)` expression form over an already-acquired local.)
    public static void Run()
    {
        var r = new Res();
        using (r)
        {
            r.Work();
        }
    }
}
