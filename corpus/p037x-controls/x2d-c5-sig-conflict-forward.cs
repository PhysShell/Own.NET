// P-037-X Stage 2d hostile control X2D-C5: a parameter forwarded to a same-name callee whose sig
// matches no record (a third, expression-bodied overload — no record — reached with bool
// constants so that no argument is opaque and the identity conflict is the only reason left).
// An identity conflict is NOT absence: R6 does not apply, the forward stays a forward, and the
// coordinate is NO_GUARDED_EVIDENCE(via:callee_sig) — never a value read off the legacy op at
// that line.
using System.IO;

static class X2dC5
{
    static void Take(Stream s, bool keep)
    {
        if (!keep)
        {
            s.Dispose();
        }
    }

    static void Take(Stream s)
    {
        s.Dispose();
    }

    static void Take(Stream s, bool keep, bool extra) => s.Dispose();

    static void Fwd(Stream s)
    {
        Take(s, true, false);
    }

    static void Caller(string path)
    {
        var r = File.OpenRead(path);
        Fwd(r);
    }
}
