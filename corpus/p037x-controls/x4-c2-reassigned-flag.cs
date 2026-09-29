// P-037-X Stage 4 hostile control X4-C2 (frozen in paper-eval/p037-max/stage4-relational-prereg-v1.json):
// a flag reassigned between production and the guarded call must degrade. `owns` is written after
// its binding, so it is not stable (G-V4 applied to a local): the sidecar carries the argument as
// opaque, no witness identity reaches the site, no discharge — the frozen collapse and OWN051.
using System;

sealed class R : IDisposable
{
    public void Touch() { }
    public void Dispose() { }
}

static class X4C2
{
    static readonly R s_shared = new R();

    static bool Cond() => DateTime.Now.Ticks % 2 == 0;

    static (R Res, bool Owns, R Shared) Produce()
    {
        if (Cond())
        {
            var r = new R();
            return (r, true, s_shared);
        }
        return (s_shared, false, s_shared);
    }

    static void Consume(R r, bool owns)
    {
        if (owns)
        {
            r.Dispose();
        }
    }

    static void Reassigned()
    {
        (R r, bool owns, R _) = Produce();
        owns = false;
        Consume(r, owns);
    }
}
