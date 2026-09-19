using System;
using System.IO;

// A2.2-3P: a local handle handed to a delegate is an escape for the legacy pass; no record. The
// orphan carries the delegate invocation (callee/sig null, first_party false).
static class ShapeOrphanDelegateLocal
{
    static void Caller(string path, Action<Stream> a) { var s = File.OpenRead(path); a(s); }
}
