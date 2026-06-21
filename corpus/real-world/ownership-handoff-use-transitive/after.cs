using System;
using System.IO;

// FIX: read the stream BEFORE handing ownership to the consumer chain, so nothing touches it
// after the handoff. Same transitive handoff (Consume -> Inner -> Dispose), correct order. The
// handoff still discharges ownership (Inner closes it), so there is no leak and no
// use-after-handoff -- the case must stay SILENT (this is the no-false-positive arm).
static class HandoffUseTransitive
{
    static void Inner(Stream s)
    {
        s.CopyTo(Stream.Null);
        s.Dispose();
    }

    static void Consume(Stream sink)
    {
        Inner(sink);
    }

    static long Run(string path)
    {
        var s = File.OpenRead(path);
        var len = s.Length;             // read BEFORE the handoff
        Consume(s);                     // ownership moves to Consume -> Inner (disposed)
        return len;                     // no use after the handoff -> silent
    }
}
