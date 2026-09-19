// The same call with `false`. The two constants must be distinguishable in the
// facts: a single "is a constant" bit would collapse the exact distinction the
// cell selection turns on.
using System.IO;

static class ShapeConstFalse
{
    static void Inner(Stream s, bool keep)
    {
        if (!keep)
        {
            s.Dispose();
        }
    }

    static void Caller(string path)
    {
        var r = File.OpenRead(path);
        Inner(r, false);
    }
}
