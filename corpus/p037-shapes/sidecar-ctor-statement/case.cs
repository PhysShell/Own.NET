using System;
using System.IO;

// A2.2-2: a constructor call as an expression statement. `keep` is a second tracked local so the
// method is flow-analysed at all (the discarded wrapper leaves nothing for the legacy to track).
static class ShapeCtorStatement
{
    sealed class Wrapper : IDisposable { public Wrapper(Stream s, bool leaveOpen) { } public void Dispose() { } }
    static void Caller(string path)
    {
        var keep = File.OpenRead(path);
        var s = File.OpenRead(path);
        new Wrapper(s, true);
        keep.Dispose();
    }
}
