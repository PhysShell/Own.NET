// FIXED (synthetic conformance, P-037 §8 row 4). Read before the handoff; the
// helper still disposes the stream, so nothing leaks and nothing is used after.
using System;
using System.IO;

static class NullGuard
{
    static void Close(Stream s)
    {
        if (s != null)
        {
            s.Dispose();
        }
    }

    static long Run(string path)
    {
        var s = File.OpenRead(path);
        long len = s.Length;
        Close(s);
        return len;
    }
}
