using System;
using System.IO;

// A2.2-4R6: a struct's method is outside the legacy pass's class enumeration (no functions[]
// record, ever); its raw call fact rides in the orphan carrier through the guarded-only member
// enumeration, exactly as a class's expression-bodied member does.
static class ShapeOrphanStructMethod
{
    static void Inner(Stream s, bool leaveOpen) { if (!leaveOpen) s.Dispose(); }
    struct Holder
    {
        public void Forward(MemoryStream r) { Inner(r, true); }
    }
}
