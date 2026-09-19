using System;
using System.IO;

// A2.2-2: `Use(new Wrapper(s, true))`. The constructor call is relevant (s flows into it) and gets
// its own call fact with form `expression`; `Use` receives an `object_creation` argument, which
// is NOT a handle, so `Use` gets no call fact: nested handles never propagate relevance outward.
static class ShapeCtorExpressionNested
{
    sealed class Wrapper : IDisposable { public Wrapper(Stream s, bool leaveOpen) { } public void Dispose() { } }
    static void Use(Wrapper w) { }
    static void Caller(string path)
    {
        var keep = File.OpenRead(path);
        var s = File.OpenRead(path);
        Use(new Wrapper(s, true));
        keep.Dispose();
    }
}
