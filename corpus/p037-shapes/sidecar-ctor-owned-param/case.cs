using System;
using System.IO;

// A2.2-2: an owned parameter flowing into a constructor is a `param` fact on the constructor call.
static class ShapeCtorOwnedParam
{
    sealed class Wrapper : IDisposable { public Wrapper(Stream s, bool leaveOpen) { } public void Dispose() { } }
    static void Caller(Stream p) { var w = new Wrapper(p, false); }
}
