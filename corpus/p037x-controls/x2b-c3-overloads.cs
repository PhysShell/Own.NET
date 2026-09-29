// P-037-X Stage 2b hostile control X2B-C3: two overloads of one name — one guarded (Split),
// one a straight-line consumer (Uncond(must), an R1 leaf) — plus an expression-bodied third
// overload that carries NO record. R2: the two records are distinct coordinates keyed by
// `Take(sig)`; the guarded caller selects by its constant; the consumer caller gets consume;
// the call into the record-less overload has a sig matching no record of that name and is
// NO_GUARDED_EVIDENCE, never resolved by name to one of the other two.
using System.IO;

static class X2bC3
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

    static void Take(Stream s, int times) => s.Dispose();

    static void GuardedCaller(string path)
    {
        var r = File.OpenRead(path);
        Take(r, false);
    }

    static void ConsumerCaller(string path)
    {
        var r = File.OpenRead(path);
        Take(r);
    }

    static void NoRecordCaller(string path)
    {
        var r = File.OpenRead(path);
        Take(r, 2);
    }
}
