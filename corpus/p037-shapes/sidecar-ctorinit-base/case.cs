using System;
using System.IO;

// A2.2-4R5: a constructor initializer is a call site of its own (call_kind constructor_initializer).
// The owned parameter flows into the base constructor's declared ordinal 0; the forwarding
// constructor's body is empty, so the legacy pass lowers nothing and the orphan carrier holds
// the fact. The base constructor's own record shows the ordinary consuming body.
static class ShapeCtorInitBase
{
    class Holder : IDisposable
    {
        readonly Stream _s;
        public Holder(Stream s, bool leaveOpen) { _s = s; if (!leaveOpen) s.Dispose(); }
        public void Dispose() { }
    }
    sealed class Forwarding : Holder
    {
        public Forwarding(MemoryStream r) : base(r, true) { }
    }
    static void Caller() { var r = new MemoryStream(); var f = new Forwarding(r); f.Dispose(); }
}
