// P-037-X Stage 2d hostile control X2D-C2: the case-4 shape, synthetic — the parameter is handed
// to an external delegate call in a declaration initializer (an R5 use) and then released on the
// same path under a guard. R6: the initializer call is the path's borrow, not an action, so the
// coordinate reads Split(dispose) [must, no]; a constant false at the guard ordinal -> borrow ->
// the caller's handle stays tracked (and is disposed: clean); true -> consume (clean).
using System;
using System.IO;

static class X2dC2
{
    static void N(Stream p, Func<Stream, int> f, bool dispose)
    {
        var n = f(p);
        if (dispose)
        {
            p.Dispose();
        }
        _ = n;
    }

    static void Keeps(string path, Func<Stream, int> f)
    {
        var r = File.OpenRead(path);
        N(r, f, false);
        r.Dispose();
    }

    static void Hands(string path, Func<Stream, int> f)
    {
        var r = File.OpenRead(path);
        N(r, f, true);
    }
}
