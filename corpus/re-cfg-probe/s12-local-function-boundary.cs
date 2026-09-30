// Stage 2A shape s12: the release sits in a local function that is called unconditionally, and in a lambda that is
// stored. Truth: FinishLocal consumes r (must) via Inner(); FinishLambda does NOT (the release is deferred).
using System;
sealed class R : IDisposable { public bool IsOpen => true; public void Touch() { } public void Dispose() { } }
static class S12
{
    static Action? s_later;

    static void FinishLocal(R r)
    {
        void Inner()
        {
            r.Dispose();
        }
        Inner();
    }

    static void FinishLambda(R r)
    {
        s_later = () => r.Dispose();
    }
}
