using System;
using System.IO;

// A2.2-2b: `a.Invoke(s)` is the same delegate invocation as `a(s)`; Roslyn binds both to the
// delegate's Invoke, and the fact is the same family.
static class ShapeDelegateExplicitInvoke
{
    static void Caller(string path, Action<Stream> a)
    {
        var keep = File.OpenRead(path);
        var s = File.OpenRead(path);
        a.Invoke(s);
        keep.Dispose();
    }
}
