// P-037 B1 acceptance fixtures (tests only; never part of the frozen shadow
// population, docs/notes/p037-phase-b1-shadow.md §E / G14). The committed
// B1.facts.json is this file through the extractor:
//   dotnet <extractor> B1.cs --flow-locals -o B1.facts.json
using System.IO;

static class K7
{
    static bool Flag() => true;

    // (pos, neg) = (bot, must): the positive cell is only a same-SCC forward.
    static void Rec(Stream s, bool keep)
    {
        if (!keep)
        {
            s.Dispose();
        }
        else
        {
            Rec(s, keep);
        }
    }

    // Unselected (call result at the guard slot): the K7 witness and A13.
    static void Caller(Stream s)
    {
        Rec(s, Flag());
    }
}

static class Pass
{
    static void Inner(Stream s, bool keep)
    {
        if (!keep)
        {
            s.Dispose();
        }
    }

    // Id edge: the caller's own guard passes through (G-S1 import, A2).
    static void Outer(Stream s, bool keep)
    {
        Inner(s, keep);
    }

    // Selected sites: a literal at the callee's elected guard (G-A1).
    static void KeepIt(Stream s)
    {
        Inner(s, true);
    }

    static void DropIt(Stream s)
    {
        Inner(s, false);
    }
}

static class Absence
{
    static void Inner(Stream s, bool keep)
    {
        if (!keep)
        {
            s.Dispose();
        }
    }

    // No functions[] record (R): expression-bodied.
    static void Bodied(Stream s, bool keep) => Inner(s, keep);

    static void ToBodied(Stream s)
    {
        Bodied(s, true);
    }

    // A record without a sidecar: a local release is indistinguishable from
    // a folded call without one (A11).
    static void Leaf(Stream s)
    {
        s.Dispose();
    }

    static void ToLeaf(Stream s, bool keep)
    {
        if (keep)
        {
            return;
        }
        Leaf(s);
    }
}
