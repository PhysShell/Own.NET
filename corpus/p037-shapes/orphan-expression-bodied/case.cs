using System;
using System.IO;

// A2.2-4R6: an expression-bodied method has no block body, so the legacy pass never visits it
// (no functions[] record, ever); its raw call fact rides in the orphan carrier through the
// guarded-only member enumeration. The block-bodied twin keeps its legacy record.
static class ShapeOrphanExpressionBodied
{
    static void Inner(Stream s, bool leaveOpen) { if (!leaveOpen) s.Dispose(); }
    static void Forward(MemoryStream r) => Inner(r, true);
    static void Block(MemoryStream r) { Inner(r, true); }
}
