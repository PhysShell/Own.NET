using System;
using System.IO;

// A2.2-2b (formal note §10.6.2, call-like): `a(p)` on a delegate-typed `a` is a call site of its
// own. The target is unknown by construction: callee and sig are null, first_party is false, and
// nothing guesses which method the delegate holds; the delegate's Invoke declared parameters still
// bind the arguments by ordinal. Tagged `call_kind: delegate_invocation`. The handle is an OWNED
// parameter so the record exists regardless of the legacy escape admission.
static class ShapeDelegateInvokeOwnedParam
{
    static void Caller(Stream p, Action<Stream> a) { a(p); }
}
