// The argument is an arbitrary expression. a2 records {"kind":"opaque"} and
// stops. It must NOT serialise `"expr": "n > 0 && !flag"` for Rust to parse
// later: humanity already has one C# front end and does not need a second one
// written by accident inside a summary engine.
using System.IO;

static class ShapeOpaqueArg
{
    static void Inner(Stream s, bool keep)
    {
        if (!keep)
        {
            s.Dispose();
        }
    }

    static void Caller(string path, int n, bool flag)
    {
        var r = File.OpenRead(path);
        Inner(r, n > 0 && !flag);
    }
}
