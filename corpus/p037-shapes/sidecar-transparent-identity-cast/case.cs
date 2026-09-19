using System;
using System.IO;

// A2.2-1: a cast to the handle's own static type is an identity conversion: transparent.
static class ShapeTransparentIdentityCast
{
    static void Inner(Stream s, bool leaveOpen) { if (!leaveOpen) s.Dispose(); }
    static void Caller(string path) { var s = File.OpenRead(path); Inner((FileStream)s, true); }
}
