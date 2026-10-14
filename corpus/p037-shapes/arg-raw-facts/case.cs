// Required control (A2.2, #304): the raw argument facts that are NOT a
// handle. A relevant call (the local `r` flows into it) carries, in its other
// slot, `null` -> null_literal, `new MemoryStream()` -> object_creation, and
// a call's result -> call_result{callee, sig}. Freshness of that result is a
// summary conclusion, so no `fresh_owned` is ever written. The creation and
// the inner call have no handle argument of their own, so neither gets a
// calls[] record: G-A records a creation only when a handle flows into it.
using System.IO;

static class ShapeRawArgFacts
{
    static void Keep(Stream s, Stream? other, bool keep)
    {
        if (!keep)
        {
            s.Dispose();
        }
    }

    static Stream Open(string path) => File.OpenRead(path);

    static void NullArg(string path)
    {
        var r = File.OpenRead(path);
        Keep(r, null, true);
        r.Dispose();
    }

    static void CreationArg(string path)
    {
        var r = File.OpenRead(path);
        Keep(r, new MemoryStream(), true);
        r.Dispose();
    }

    static void CallResultArg(string path)
    {
        var r = File.OpenRead(path);
        Keep(r, Open(path), true);
        r.Dispose();
    }
}
