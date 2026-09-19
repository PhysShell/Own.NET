using System;
using System.IO;

// A2.2-1 NEGATIVE: `TakeXBox((XBox)s)` is a cast by syntax and a user-defined explicit operator
// by semantics, hidden inside the cast expression ((XBox)s already has type XBox at the call).
// user_conversion wins over the transparent-looking cast: NOT relevant, no call fact.
static class ShapeUserConvExplicit
{
    sealed class XBox { public static explicit operator XBox(FileStream f) => new XBox(); }
    static void TakeXBox(XBox b) { }
    static void Caller(string path)
    {
        var keep = File.OpenRead(path);
        var s = File.OpenRead(path);
        TakeXBox((XBox)s);
        keep.Dispose();
        s.Dispose();
    }
}
