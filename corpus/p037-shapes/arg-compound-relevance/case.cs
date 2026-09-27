// A2.2 G-D: a handle inside a compound argument (`as`, `?:`, `??`) cannot be
// represented precisely, so the slot is opaque — but the handle still flows
// into the call, so the call record must exist (opaque, not absent; the same
// rule A' applied to params/ref/out slots).
using System.IO;

static class ShapeCompound
{
    static void Keep(Stream s, bool keep)
    {
        if (!keep)
        {
            s.Dispose();
        }
    }

    static void As(Stream p, bool keep)
    {
        Keep(p as Stream, keep);
    }

    static void Conditional(Stream p, Stream q, bool c)
    {
        Keep(c ? p : q, true);
    }

    static void Coalesce(Stream? p, Stream q)
    {
        Keep(p ?? q, false);
    }
}
