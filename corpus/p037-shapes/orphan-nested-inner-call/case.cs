using System;
using System.IO;

// A2.2-3P: `Use(Wrap(s))` — every handle escapes, no record. The orphan carries exactly the
// INNER call (`Wrap(s)`, direct); the outer `Use` receives a call result and gets no fact:
// nested_call_result is a named exclusion for the outer call, never a fact of its own.
static class ShapeOrphanNestedInnerCall
{
    static Stream Wrap(Stream s) => s;
    static void Use(Stream s) { }
    static void Caller(string path) { var s = File.OpenRead(path); Use(Wrap(s)); }
}
