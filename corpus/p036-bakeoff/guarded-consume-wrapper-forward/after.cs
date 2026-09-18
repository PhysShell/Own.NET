// FIXED (synthetic conformance, P-037 §8 row 7). `Outer(s, false)` selects
// Inner's consume cell one hop up -> clean.
using System;
using System.IO;

static class GuardedWrapper
{
    static void Inner(Stream s, bool keep)
    {
        if (!keep)
        {
            s.Dispose();
        }
    }

    static void Outer(Stream s, bool keep)
    {
        Inner(s, keep);
    }

    static long Fine(string path)
    {
        var s = File.OpenRead(path);
        long len = s.Length;
        Outer(s, keep: false);
        return len;
    }
}
