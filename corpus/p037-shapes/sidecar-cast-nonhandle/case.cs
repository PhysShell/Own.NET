using System;
using System.IO;

// A2.2-1 NEGATIVE: a transparent wrapper around a NON-handle creates no relevance. The cast
// unwraps to a static property, which is opaque and not a handle of this method.
static class ShapeCastNonHandle
{
    static void Inner(Stream s, bool leaveOpen) { if (!leaveOpen) s.Dispose(); }
    static void Caller(string path)
    {
        var keep = File.OpenRead(path);
        Inner((Stream)Stream.Null, true);
        keep.Dispose();
    }
}
