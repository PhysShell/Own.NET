using System;
using System.IO;

// A2.2-2b: named arguments on a delegate invocation resolve against the delegate's DECLARED
// parameter names, so the ordinals are Invoke's, not the source positions.
static class ShapeDelegateNamedArgs
{
    delegate void Sink(Stream stream, bool leaveOpen);
    static void Caller(string path, Sink d)
    {
        var keep = File.OpenRead(path);
        var s = File.OpenRead(path);
        d(leaveOpen: true, stream: s);
        keep.Dispose();
    }
}
