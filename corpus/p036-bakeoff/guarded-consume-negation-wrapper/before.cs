// BUGGY (synthetic conformance, P-037 §8 row 8 — the wrapper NEGATES the flag
// on the edge: `Inner(s, !stop)`; the cells swap).
using System;
using System.IO;

static class GuardedNegation
{
    static void Inner(Stream s, bool keep)
    {
        if (!keep)
        {
            s.Dispose();
        }
    }

    static void Outer(Stream s, bool stop)
    {
        Inner(s, !stop);                   // stop == false  =>  keep == true
    }

    static long Leak(string path)
    {
        var s = File.OpenRead(path);
        long len = s.Length;
        Outer(s, stop: false);             // Inner(s, keep: true) never disposes -> leak
        return len;
    }
}
