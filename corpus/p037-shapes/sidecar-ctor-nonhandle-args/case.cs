using System;
using System.IO;

// A2.2-2 NEGATIVE: a constructor call with no handle among its arguments is not relevant.
static class ShapeCtorNonHandleArgs
{
    sealed class Wrapper : IDisposable { public Wrapper(Stream s, bool leaveOpen) { } public void Dispose() { } }
    static void Caller(string path)
    {
        var keep = File.OpenRead(path);
        var w = new Wrapper(Stream.Null, true);
        keep.Dispose();
    }
}
