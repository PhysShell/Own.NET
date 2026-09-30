// Stage 2A shape s10: the relational pair through deconstruction. Truth: a is released iff owns; with the producer's
// fresh_iff relation the site discharges (P-037-X Stage 4); a body-only view of Consume says may.
using System;
sealed class R : IDisposable { public bool IsOpen => true; public void Touch() { } public void Dispose() { } }
static class S10
{
    static readonly R s_shared = new R();

    static bool Cond() => DateTime.Now.Ticks % 2 == 0;

    static (R Res, bool Owns) Produce()
    {
        if (Cond())
        {
            var r = new R();
            return (r, true);
        }
        return (s_shared, false);
    }

    static void Consume(R a, bool owns)
    {
        if (owns)
        {
            a.Dispose();
        }
    }

    static void Run()
    {
        (R a, bool owns) = Produce();
        Consume(a, owns);
    }
}
