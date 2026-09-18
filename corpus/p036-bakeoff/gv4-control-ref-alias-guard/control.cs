// NEGATIVE CONTROL (class 4, P-037 §8 row 18b, G-V4 — the ref-alias twin of
// row 18a). No direct `g = ...` anywhere: a writable ref-local is created over
// the guard and negated through the alias. G-V4 disqualifies the guard on the
// alias's CREATION alone (fail-closed, no alias tracking): the forward is
// `opaque`, `Outer(r, true)` lowers to plain + OWN051, and the caller's
// defensive dispose is never a false OWN003.
// Required after A1: NO findings. MEASURED TODAY: a FALSE OWN003 on the
// defensive dispose (the may-as-must ConsumesParam hole, as in row 18a).
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
        ref bool a = ref g;     // G-V4 disqualifier: a writable alias of the guard
        a = !a;                 // the write goes through the alias
        Inner(p, g);            // syntactically identity, semantically negated
    }

    public static void Use()
    {
        var r = new Res();
        Outer(r, true);         // Inner receives false: r is NOT disposed here
        r.Dispose();            // honest defensive dispose — never OWN003
    }
}
