using System;
using System.IO;

// A2.2-2b: a disposable local into a delegate invocation. `keep` is a second tracked local so
// the method is flow-analysed at all (a handle handed to a delegate is an escape for the legacy).
static class ShapeDelegateInvokeLocalKeep
{
    static void Caller(string path, Action<Stream> a)
    {
        var keep = File.OpenRead(path);
        var s = File.OpenRead(path);
        a(s);
        keep.Dispose();
    }
}
