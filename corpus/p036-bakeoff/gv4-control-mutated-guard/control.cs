// NEGATIVE CONTROL (class 4, P-037 §8 row 18a, G-V4 — not a bug fixture).
// The wrapper flips its guard before forwarding it: `Inner` receives `!g`, so
// `Outer(r, true)` never disposes `r`. A summary that read the *syntactic*
// identity forward `Inner(p, g)` as an `id` edge would select Inner's positive
// cell and fabricate `must` for `Outer(r, true)` — and the caller's honest
// defensive dispose below would be charged a false OWN003. G-V4 makes the
// mutated guard ineligible: the edge degrades to `opaque` (join(must, no) =
// may), the call lowers to plain + OWN051, and the defensive dispose is fine.
// Required after A1: NO findings. MEASURED TODAY (Owen at 70189a3): a FALSE
// OWN003 on the defensive dispose — the extractor's flow-insensitive
// ConsumesParam lowers `Inner(p, g)` to a release because Inner disposes on
// SOME path (the may-as-must hole, A1's first bug). Red until A1 lands.
using System;

public sealed class Res : IDisposable
{
    public void Dispose() { }
}

public static class Guarded
{
    public static void Inner(Res p, bool g)
    {
        if (g)
        {
            p.Dispose();
        }
    }

    public static void Outer(Res p, bool g)
    {
        g = !g;                 // G-V4 disqualifier: a direct write to the guard
        Inner(p, g);            // syntactically an identity forward — semantically negated
    }

    public static void Use()
    {
        var r = new Res();
        Outer(r, true);         // Inner receives false: r is NOT disposed here
        r.Dispose();            // honest defensive dispose — never OWN003
    }
}
