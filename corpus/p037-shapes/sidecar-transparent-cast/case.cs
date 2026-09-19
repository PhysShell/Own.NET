using System;
using System.IO;

// A2.2-1 (formal note §10.6.3): an explicit reference UPCAST is a transparent wrapper.
// The same value reaches the callee, so the slot is the unwrapped `var` fact and the
// call is relevant. Before A2.2-1 the cast hid the handle and the whole call vanished.
static class ShapeTransparentCast
{
    static void Inner(Stream s, bool leaveOpen) { if (!leaveOpen) s.Dispose(); }
    static void Caller(string path) { var s = File.OpenRead(path); Inner((Stream)s, true); }
}
