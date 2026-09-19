// A wrapper FORWARDS its own flag unchanged: `Inner(s, keep)`. a2 records
// {"param":1,"kind":"param","source_param":1}; Rust reads the `id` edge.
using System.IO;

static class ShapeForwardBare
{
    static void Inner(Stream s, bool keep)
    {
        if (!keep)
        {
            s.Dispose();
        }
    }

    static void Outer(Stream s, bool keep)
    {
        Inner(s, keep);
    }
}
