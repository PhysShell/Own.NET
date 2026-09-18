// BUGGY (synthetic conformance, P-037 §8 row 2 — the same guard spelled as an
// early return; the two spellings must converge in a guarded summary).
using System;
using System.IO;

static class GuardedEarlyReturn
{
    static void Close(Stream s, bool keep)
    {
        if (keep)
            return;
        s.Dispose();
    }

    static long Leak(string path)
    {
        var s = File.OpenRead(path);
        long len = s.Length;
        Close(s, keep: true);              // returns before the Dispose -> leak
        return len;
    }
}
