// P-037-X Stage 2d hostile control X2D-C4: a release, then a use at an external call line on the
// same path (a use after dispose inside the callee). R6: the release is the path's action and the
// later external use is a borrow, so the coordinate reads Uncond(must); the legacy engines' own
// verdict inside the callee is unchanged; the caller that hands the handle off is clean.
using System;
using System.IO;

static class X2dC4
{
    static void RelThenUse(Stream p)
    {
        p.Dispose();
        Console.WriteLine(p);
    }

    static void Caller(string path)
    {
        var r = File.OpenRead(path);
        RelThenUse(r);
    }
}
