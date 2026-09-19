// `Inner(s, true)`: a BOOL CONSTANT argument. a2 must record it as
// {"param":1,"kind":"bool_const","value":true}; Rust derives `const-pos`.
// The frontend never names const-pos itself — that is an interpretation
// relative to the callee's elected guard, and it belongs to Rust.
using System.IO;

static class ShapeConstTrue
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
        Inner(r, true);
    }
}
