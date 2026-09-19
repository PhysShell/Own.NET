using System;
using System.IO;

// A2.2-1: `??` is a MAY-VALUE form: the handle is one alternative; relevant, opaque slot.
static class ShapeMayValueCoalesce
{
    static void Inner(Stream s, bool leaveOpen) { if (!leaveOpen) s.Dispose(); }
    static void Caller(string path, Stream? p)
    {
        var s = File.OpenRead(path);
        Inner(p ?? s, true);
    }
}
