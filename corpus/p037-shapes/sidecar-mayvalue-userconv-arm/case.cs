using System;
using System.IO;

// A2.2-1 NEGATIVE: an alternative counts only through value-preserving edges. Here both arms
// are handles, but the conditional's value passes through op_Implicit before reaching TakeBox:
// not a handle alternative, NOT relevant, no call fact.
static class ShapeMayValueUserConvArm
{
    sealed class Box { public static implicit operator Box(FileStream f) => new Box(); }
    static void TakeBox(Box b) { }
    static void Caller(string path, bool flag)
    {
        var keep = File.OpenRead(path);
        var s = File.OpenRead(path);
        var t = File.OpenRead(path);
        TakeBox(flag ? s : t);
        keep.Dispose();
        s.Dispose();
        t.Dispose();
    }
}
