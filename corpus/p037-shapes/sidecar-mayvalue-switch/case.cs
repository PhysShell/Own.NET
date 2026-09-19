using System;
using System.IO;

// A2.2-1: a switch expression is a MAY-VALUE form: any arm yielding a handle keeps the call
// relevant; the slot stays opaque.
static class ShapeMayValueSwitch
{
    static void Inner(Stream s, bool leaveOpen) { if (!leaveOpen) s.Dispose(); }
    static void Caller(string path, int k)
    {
        var s = File.OpenRead(path);
        var t = File.OpenRead(path);
        Inner(k switch { 0 => s, _ => t }, true);
    }
}
