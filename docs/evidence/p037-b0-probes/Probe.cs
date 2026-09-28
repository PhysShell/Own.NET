using System.IO;

static class Probe
{
    static void Inner(Stream s, bool keep)
    {
        if (!keep)
        {
            s.Dispose();
        }
    }

    static void Sink(Stream s) { s.Dispose(); }

    // forward under the positive literal, statement-level (no body op)
    static void Branchy(Stream s, bool keep)
    {
        if (keep)
        {
            Inner(s, true);
        }
        else
        {
            Sink(s);
        }
    }

    // two eligible ifs on ONE line
    static void TwoIfs(Stream s, bool a, bool b)
    {
        if (a) { Inner(s, true); } if (b) { Sink(s); }
    }

    // early-return guard
    static void Early(Stream s, bool keep)
    {
        if (keep) return;
        Sink(s);
    }
}
