using System;
using System.IO;

// A2.2-1: the null-forgiving `!` is not a conversion at all; Roslyn attaches the argument
// operation to the inner identifier. Transparent.
static class ShapeTransparentBang
{
    static void Inner(Stream s, bool leaveOpen) { if (!leaveOpen) s.Dispose(); }
    static void Caller(string path) { var s = File.OpenRead(path); Inner(s!, true); }
}
