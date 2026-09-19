using System;
using System.IO;

// A2.2-1: `s as FileStream` on a Stream-typed handle is NOT guaranteed by the static type: it
// yields the handle or null. May-value: relevant, opaque slot (contrast sidecar-transparent-as-upcast).
static class ShapeMayValueAsDowncast
{
    static void InnerF(FileStream f, bool leaveOpen) { if (!leaveOpen) f.Dispose(); }
    static void Caller(string path)
    {
        Stream s = File.OpenRead(path);
        InnerF(s as FileStream, true);
    }
}
