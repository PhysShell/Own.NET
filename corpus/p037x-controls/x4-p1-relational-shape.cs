// P-037-X Stage 4 positive control X4-P1 (frozen in paper-eval/p037-max/stage4-relational-prereg-v1.json):
// the abstract (resource, ownsResource) shape. Produce hands back a fresh R together with the
// literal true, or the shared R together with false (R4-1: slot 0 is fresh iff slot 1). A caller
// deconstructs the pair (R4-2) and hands the resource with ITS OWN flag to a guarded consumer
// whose cells are (must, no): the obligation is discharged by the relation (R4-5). Always
// discharges by must; Never leaves the owned path unreleased -> OWN001 with the opt-in on.
using System;

sealed class R : IDisposable
{
    public void Touch() { }
    public void Dispose() { }
}

static class X4P1
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

    static void Always(R r)
    {
        r.Dispose();
    }

    static void Never(R r)
    {
        r.Touch();
    }

    static void Matched()
    {
        (R r, bool owns, R shared) = Produce();
        try
        {
            r.Touch();
        }
        finally
        {
            Consume(r, owns);
        }
    }

    static void MatchedPlain()
    {
        var (r, owns, _) = Produce();
        Consume(r, owns);
    }

    static void AlwaysCaller()
    {
        (R r, bool owns, R _) = Produce();
        Always(r);
    }

    static void NeverCaller()
    {
        (R r, bool owns, R _) = Produce();
        Never(r);
    }
}
