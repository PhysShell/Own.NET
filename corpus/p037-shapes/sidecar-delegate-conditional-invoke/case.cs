using System;
using System.IO;

// A2.2-2b: `a?.Invoke(s)` is still the delegate's Invoke; the site is the invocation inside the
// conditional access and the form is whatever the syntactic position says.
static class ShapeDelegateConditionalInvoke
{
    static void Caller(string path, Action<Stream>? a)
    {
        var keep = File.OpenRead(path);
        var s = File.OpenRead(path);
        a?.Invoke(s);
        keep.Dispose();
    }
}
