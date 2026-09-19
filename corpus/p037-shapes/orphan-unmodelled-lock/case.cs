using System;
using System.IO;

// A2.2-3P: `lock` is a construct the legacy pass does not model (measured: lock, goto and a
// local-function declaration are skipped; try, switch, for and using declarations are
// modelled), so the method is honestly skipped and gets no functions[] record. Its raw call
// fact is still honest and rides in the orphan carrier.
static class ShapeOrphanUnmodelledLock
{
    static readonly object Gate = new object();
    static void Inner(Stream s, bool leaveOpen) { if (!leaveOpen) s.Dispose(); }
    static void Caller(string path)
    {
        var s = File.OpenRead(path);
        lock (Gate) { Inner(s, true); }
    }
}
