using System;

// A2.2-1a NEGATIVE (formal note §10.6.3): a disposable STRUCT handle passed to an `object`
// parameter is boxed — the callee receives a copy, not the ownership identity of the value.
// `boxing` is a conversion edge and `boxing_conversion` a named exclusion: NOT relevant, no
// call fact. The handle is an OWNED PARAMETER so the method record exists independently of the
// legacy escape admission, and `Control` proves the same struct parameter IS a handle when it is
// passed without boxing: the classifier, not a missing record, is what this shape tests.
static class ShapeBoxingStructHandle
{
    struct Token : IDisposable { public void Dispose() { } }
    static void Sink(object x) { }
    static void SinkT(Token t) { }
    static void Caller(Token r) { Sink(r); }
    static void Control(Token r) { SinkT(r); }
}
