// FIXED (synthetic conformance, P-037 §8 row 2). `keep: false` reaches the
// Dispose on the only path -> clean.
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

    static long Fine(string path)
    {
        var s = File.OpenRead(path);
        long len = s.Length;
        Close(s, keep: false);
        return len;
    }
}
