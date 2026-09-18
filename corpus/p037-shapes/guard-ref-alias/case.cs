// The guard is handed to a `ref` parameter before the branch reads it, so a
// callee may have changed it. Same G-V4 verdict as a direct write: not
// eligible, no guard metadata.
using System.IO;

static class ShapeRefAliasGuard
{
    static void Flip(ref bool b)
    {
        b = !b;
    }

    static void Inner(Stream p, bool keep)
    {
        Flip(ref keep);
        if (!keep)
        {
            p.Dispose();
        }
    }

    static void Caller(string path)
    {
        var r = File.OpenRead(path);
        Inner(r, true);
        r.Dispose();
    }
}
