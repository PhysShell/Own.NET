using System;
using System.IO;

// A2.2-2: target-typed `new(...)` is the same constructor call; the site is the `new` expression.
static class ShapeCtorImplicitNew
{
    sealed class Wrapper : IDisposable { public Wrapper(Stream s, bool leaveOpen) { } public void Dispose() { } }
    static void Caller(string path) { var s = File.OpenRead(path); Wrapper w = new(s, true); }
}
