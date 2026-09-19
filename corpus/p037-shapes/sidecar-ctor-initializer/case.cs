using System;
using System.IO;

// A2.2-2 (formal note §10.6.2, call-like): a constructor call is a call site of its own.
// `var w = new Wrapper(s, true)` binds `s` to the constructor's declared ordinal 0; the callee is
// the constructor's functions[] key (`{Type}..ctor`), the form is `initializer`, and the fact
// carries `call_kind: object_creation` (an invocation carries no call_kind at all).
static class ShapeCtorInitializer
{
    sealed class Wrapper : IDisposable { public Wrapper(Stream s, bool leaveOpen) { } public void Dispose() { } }
    static void Caller(string path) { var s = File.OpenRead(path); var w = new Wrapper(s, true); }
}
