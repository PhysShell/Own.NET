using System;
using System.IO;

// A2.2-3P: a constructor call as a statement, wrapper discarded: the legacy pass tracks nothing
// and emits no record; the orphan carries the constructor call (object_creation).
static class ShapeOrphanCtorStatement
{
    sealed class Wrapper : IDisposable { public Wrapper(Stream s, bool leaveOpen) { } public void Dispose() { } }
    static void Caller(string path) { var s = File.OpenRead(path); new Wrapper(s, true); }
}
