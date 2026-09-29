// P-037-X Stage 4 carrier control X4-C5 (frozen in paper-eval/p037-max/stage4-relational-prereg-v1.json):
// an owned slot holding an untracked identifier is filled by name (R4-6) so the handle in the
// later slot is carried: r is discharged by its witness; `first` never becomes a handle.
using System;

sealed class R : IDisposable
{
    public void Touch() { }
    public void Dispose() { }
}

static class X4C5
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

    static void ConsumeSecond(R? first, R r, bool owns)
    {
        first?.Touch();
        if (owns)
        {
            r.Dispose();
        }
    }

    static void Filled()
    {
        R? first = null;
        (R r, bool owns, R _) = Produce();
        ConsumeSecond(first, r, owns);
    }
}
