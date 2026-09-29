// P-037-X Stage 2d hostile control X2D-C1 (frozen in paper-eval/p037-max/stage2d-prereg-v1.json):
// a guarded release whose other branch hands the parameter to an EXTERNAL (BCL) call in statement
// form. R6: the external call is the legacy borrow of its path, so M.p reads Split(g) [must, no];
// a caller passing true consumes, false borrows, an opaque guard argument gets plain + OWN051 —
// never consume on the borrow side.
using System;
using System.IO;

static class X2dC1
{
    static void M(Stream p, bool g)
    {
        if (g)
        {
            p.Dispose();
        }
        else
        {
            Console.WriteLine(p);
        }
    }

    static void HandsOff(string path)
    {
        var r = File.OpenRead(path);
        M(r, true);
    }

    static void Keeps(string path)
    {
        var r = File.OpenRead(path);
        M(r, false);
        r.Dispose();
    }

    static void Opaque(string path, bool flag)
    {
        var r = File.OpenRead(path);
        M(r, flag);
    }
}
