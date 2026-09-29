// P-037-X Stage 4 hostile control X4-C1 (frozen in paper-eval/p037-max/stage4-relational-prereg-v1.json):
// a boolean unrelated to the resource must NOT become an ownership witness. `other` is a stable
// boolean local, so the sidecar carries it as flag_var{other} — but r's witness is `owns`. No
// discharge: the site keeps the frozen collapse (may) and the honest OWN051 advisory.
using System;

sealed class R : IDisposable
{
    public void Touch() { }
    public void Dispose() { }
}

static class X4C1
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

    static void Unrelated()
    {
        (R r, bool owns, R _) = Produce();
        bool other = Cond();
        Consume(r, other);
    }
}
