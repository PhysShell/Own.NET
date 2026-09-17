// BUGGY (synthetic conformance, P-037 §8 row 7 — a wrapper that merely forwards
// its flag; the split is imported along the `id` edge, no literal in the
// wrapper's own body).
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
        Inner(s, keep);                    // forwards the flag unchanged
    }

    static long Leak(string path)
    {
        var s = File.OpenRead(path);
        long len = s.Length;
        Outer(s, keep: true);              // Inner(s, true) never disposes -> leak
        return len;
    }
}
