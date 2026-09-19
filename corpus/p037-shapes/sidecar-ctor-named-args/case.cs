using System;
using System.IO;

// A2.2-2: named constructor arguments bind by DECLARED ordinal, not by source position.
static class ShapeCtorNamedArgs
{
    sealed class Wrapper : IDisposable { public Wrapper(Stream s, bool leaveOpen) { } public void Dispose() { } }
    static void Caller(string path) { var s = File.OpenRead(path); var w = new Wrapper(leaveOpen: false, s: s); }
}
