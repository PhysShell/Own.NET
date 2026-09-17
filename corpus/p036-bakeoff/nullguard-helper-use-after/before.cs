// BUGGY (synthetic conformance, P-037 §8 row 4 — the defensive null-guard
// helper; the argument is a fresh, provably non-null stream, so the helper
// provably disposes it, and the read afterwards is a use-after-dispose).
//
// Today's summary derives `may` for the helper (partial release, INF-S2) and
// UNTRACKS the caller's stream at the call (INF-A5) — the use after it is
// silent, with an OWN051 advisory only.
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
        var s = File.OpenRead(path);       // fresh, non-null
        Close(s);                          // provably disposes it
        return s.Length;                   // use after dispose
    }
}
