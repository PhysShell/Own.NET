// The wrapper NEGATES the flag: `Inner(s, !stop)`. a2 records the same binding
// plus `"negated": true`; Rust reads the `neg` edge and the cells swap.
using System.IO;

static class ShapeForwardNegated
{
    static void Inner(Stream s, bool keep)
    {
        if (!keep)
        {
            s.Dispose();
        }
    }

    static void Outer(Stream s, bool stop)
    {
        Inner(s, !stop);
    }
}
