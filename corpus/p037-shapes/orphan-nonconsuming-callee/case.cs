using System;
using System.IO;

// A2.2-3P (formal note §10.6.6): `Same(s)` hands the only handle to a callee that never disposes
// it; the legacy pass reads that as an escape, nothing stays tracked, and the method gets NO
// functions[] record. Its raw fact is honest and is carried in guarded_functions[] instead.
static class ShapeOrphanNonConsumingCallee
{
    static void Same(FileStream f) { }
    static void Caller(string path) { var s = File.OpenRead(path); Same(s); }
}
