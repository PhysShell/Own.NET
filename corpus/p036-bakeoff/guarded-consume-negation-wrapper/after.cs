// FIXED (synthetic conformance, P-037 §8 row 8). `Outer(s, stop: true)` becomes
// `Inner(s, keep: false)` -> disposed -> clean.
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
        Inner(s, !stop);
    }

    static long Fine(string path)
    {
        var s = File.OpenRead(path);
        long len = s.Length;
        Outer(s, stop: true);
        return len;
    }
}
