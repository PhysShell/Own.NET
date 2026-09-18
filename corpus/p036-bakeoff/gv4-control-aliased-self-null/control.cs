// NEGATIVE CONTROL (class 4, P-037 §8 row 19, G-V4 on the self-null split).
// `Close` never writes `q` directly, but a writable ref-local rebinds it to
// `r` before the null-guarded dispose: the body disposes a DIFFERENT object
// than the caller's argument. A self-null split that ignored the alias would
// claim `Split(nn(q), must, no)` and, for a provably non-null argument, select
// `must` — charging the caller's honest dispose of `s` a false OWN003. G-V4
// disqualifies `q`: no split, today's derivation (may), plain + OWN051.
// Required after A1: NO findings. MEASURED TODAY: a FALSE OWN003 on
// `s.Dispose()` — ConsumesParam sees `q.Dispose()` somewhere in Close and
// lowers the call to a release of the caller's argument (may-as-must).
using System;
using System.IO;

public static class Guarded
{
    public static void Close(Stream q, Stream r)
    {
        ref Stream a = ref q;   // G-V4 disqualifier: writable alias of the resource parameter
        a = r;                  // q now names r
        if (q != null)
        {
            q.Dispose();        // disposes r, not the caller's argument
        }
    }

    public static void Use(Stream other)
    {
        var s = new MemoryStream();
        Close(s, other);        // s is NOT disposed by Close
        s.Dispose();            // honest dispose of the caller's own stream — never OWN003
    }
}
