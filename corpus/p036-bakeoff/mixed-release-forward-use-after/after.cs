// FIXED (synthetic conformance, P-037 §8 row 12). Read before the handoff.
using System;
using System.IO;

static class MixedRoute
{
    static void Sink(Stream s)
    {
        s.CopyTo(Stream.Null);
        s.Dispose();
    }

    static void Route(Stream s, bool direct)
    {
        if (direct)
        {
            s.Dispose();
        }
        else
        {
            Sink(s);
        }
    }

    static long Run(string path, bool direct)
    {
        var s = File.OpenRead(path);
        long len = s.Length;
        Route(s, direct);
        return len;
    }
}
