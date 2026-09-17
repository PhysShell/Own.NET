// BUGGY (synthetic conformance, P-037 §8 row 12 — release on one arm, forward
// to an unconditional consumer on the other: EVERY path consumes, so the
// summary is a unanimous `must` and no call-site selection is needed).
//
// Today's derivation gives the local release priority, sees it is partial,
// and settles on `may` (the forward is never processed) — the caller is
// untracked and the use after the call is silent.
using System;
using System.IO;

static class MixedRoute
{
    static void Sink(Stream s)
    {
        s.CopyTo(Stream.Null);
        s.Dispose();                       // unconditional consumer
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
        Route(s, direct);                  // consumed on both arms
        return s.Length;                   // use after dispose, whatever `direct` is
    }
}
