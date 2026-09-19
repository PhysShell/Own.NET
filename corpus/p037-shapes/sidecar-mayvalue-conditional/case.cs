using System;
using System.IO;

// A2.2-1: the conditional operator is a MAY-VALUE form: a handle among the alternatives keeps
// the call relevant, the slot stays `opaque` (the vocabulary has no `one of` fact; no `mentions`).
static class ShapeMayValueConditional
{
    static void Inner(Stream s, bool leaveOpen) { if (!leaveOpen) s.Dispose(); }
    static void Caller(string path, bool flag)
    {
        var s = File.OpenRead(path);
        var t = File.OpenRead(path);
        Inner(flag ? s : t, true);
    }
}
