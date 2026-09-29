// P-037-X Stage 4 hostile control X4-C3 (frozen in paper-eval/p037-max/stage4-relational-prereg-v1.json):
// two resources and one flag must not cross-associate. Crossed hands each resource the OTHER
// pair's flag: neither site carries the handle's own witness -> two OWN051, no discharge.
// Straight hands each resource its own flag -> two discharges, no code.
using System;

sealed class R : IDisposable
{
    public void Touch() { }
    public void Dispose() { }
}

static class X4C3
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

    static void Crossed()
    {
        (R a, bool fa, R _) = Produce();
        (R b, bool fb, R _) = Produce();
        Consume(a, fb);
        Consume(b, fa);
    }

    static void Straight()
    {
        (R a, bool fa, R _) = Produce();
        (R b, bool fb, R _) = Produce();
        Consume(a, fa);
        Consume(b, fb);
    }
}
