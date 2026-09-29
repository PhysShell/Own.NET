// P-037-X Stage 4 hostile control X4-C4 (frozen in paper-eval/p037-max/stage4-relational-prereg-v1.json):
// the resource -> guard association must respect the cells. ConsumeUnless releases when its
// flag is FALSE (cells [no, must]); the obligation exists when the witness is TRUE. Not the
// (must, no) match: no discharge, the frozen collapse and OWN051.
using System;

sealed class R : IDisposable
{
    public void Touch() { }
    public void Dispose() { }
}

static class X4C4
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

    static void ConsumeUnless(R r, bool keep)
    {
        if (!keep)
        {
            r.Dispose();
        }
    }

    static void Inverted()
    {
        (R r, bool owns, R _) = Produce();
        ConsumeUnless(r, owns);
    }
}
