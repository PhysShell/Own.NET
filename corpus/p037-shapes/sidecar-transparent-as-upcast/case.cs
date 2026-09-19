using System;
using System.IO;

// A2.2-1: `s as Stream` on a FileStream is a GUARANTEED reference upcast, so it is
// transparent (the may-fail `as` is a different shape: sidecar-mayvalue-as-downcast).
static class ShapeTransparentAsUpcast
{
    static void Inner(Stream s, bool leaveOpen) { if (!leaveOpen) s.Dispose(); }
    static void Caller(string path) { var s = File.OpenRead(path); Inner(s as Stream, true); }
}
