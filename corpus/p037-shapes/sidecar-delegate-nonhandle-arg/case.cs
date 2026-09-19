using System;
using System.IO;

// A2.2-2b NEGATIVE: a delegate invocation with no handle among its arguments is not relevant.
static class ShapeDelegateNonHandleArg
{
    static void Caller(string path, Action<Stream> a)
    {
        var keep = File.OpenRead(path);
        a(Stream.Null);
        keep.Dispose();
    }
}
