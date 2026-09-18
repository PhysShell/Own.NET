// BUGGY (synthetic conformance, P-037 §8 row 1 — the SectorTS `Teardown(bool)`
// shape on an IDisposable parameter).
//
// `Close(s, keep)` disposes its parameter ONLY when `keep == false`. The caller
// passes `keep: true`, so the stream is never disposed on any path -> leak.
// A context-insensitive summary can only say "may consume"; the guarded
// summary of P-037 selects the `no` cell at this call site and keeps the
// obligation with the caller.
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

    static long Leak(string path)
    {
        var s = File.OpenRead(path);
        long len = s.Length;
        Close(s, keep: true);              // provably does NOT dispose -> leak
        return len;
    }
}
