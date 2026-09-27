// Negative control for named-argument binding: two parameters of the SAME
// type, passed by name in reversed order. Positional guessing and type-based
// guessing are both wrong here; only symbolic resolution binds `b: p` to
// ordinal 1 and `a: q` to ordinal 0.
using System.IO;

static class ShapeDuplicateNamed
{
    static void Pair(Stream a, Stream b)
    {
        a.Dispose();
    }

    static void Caller(Stream p, Stream q)
    {
        Pair(b: p, a: q);
    }
}
