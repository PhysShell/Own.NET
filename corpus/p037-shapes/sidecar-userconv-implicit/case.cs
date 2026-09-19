using System;
using System.IO;

// A2.2-1 NEGATIVE: `TakeBox(s)` is a bare identifier by syntax and op_Implicit(s) by semantics.
// The value reaching the callee is a Box, not the handle: user_conversion is a named exclusion,
// the call is NOT relevant and no call fact exists. `keep` is a second, non-escaping local so the
// method is flow-analysed at all and the absence is the signal, not a missing record.
static class ShapeUserConvImplicit
{
    sealed class Box { public static implicit operator Box(FileStream f) => new Box(); }
    static void TakeBox(Box b) { }
    static void Caller(string path)
    {
        var keep = File.OpenRead(path);
        var s = File.OpenRead(path);
        TakeBox(s);
        keep.Dispose();
        s.Dispose();
    }
}
