// P-037 PCS-0 probe (docs/notes/p037-pcs0-producer-canonical-shadow.md §D), not population.
// F0: the natural transitive chain Top -> Outer -> Inner. The legacy body folds Top's
// forward into a `release` because ConsumesParam(Outer) is true; the canonical shadow must
// keep it an honest `call` so the ordinary MOS reads Outer's own `may`.
// F1: the borrow chain Pass -> Peek. The shadow forwards it just the same and the MOS, not
// the producer, keeps `no`.
using System.IO;

static class PcsTransitive
{
    static void Inner(Stream s, bool keep)
    {
        if (!keep)
            s.Dispose();
    }

    static void Outer(Stream s, bool keep)
    {
        Inner(s, keep);
    }

    static void Top(Stream s)
    {
        Outer(s, true);
    }

    static void Peek(Stream s)
    {
        s.ReadByte();
    }

    static void Pass(Stream s)
    {
        Peek(s);
    }
}
