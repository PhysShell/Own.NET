// FIXED (synthetic conformance, P-037 §8 row 1). The caller passes
// `keep: false`, so `Close` disposes the stream on its only path: the
// obligation moves into the helper and the caller must stay silent.
using System;
using System.IO;

static class Guarded
{
    static void Close(Stream s, bool keep)
    {
        if (!keep)
        {
            s.Dispose();
        }
    }

    static long Fine(string path)
    {
        var s = File.OpenRead(path);
        long len = s.Length;
        Close(s, keep: false);             // provably disposes -> clean
        return len;
    }
}
