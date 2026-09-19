using System;
using System.IO;

// A2.2-3P: one file, two methods — `Recorded` is admitted by the legacy pass (a tracked local
// disposed in place) and must NOT appear in the carrier; `Orphan` is not admitted and must
// appear ONLY there. The carrier is an orphan carrier, never a second source.
static class ShapeOrphanDisjointFromRecords
{
    static void Inner(Stream s, bool leaveOpen) { if (!leaveOpen) s.Dispose(); }
    static void Same(FileStream f) { }
    static void Recorded(string path) { var s = File.OpenRead(path); Inner(s, true); }
    static void Orphan(string path) { var s = File.OpenRead(path); Same(s); }
}
