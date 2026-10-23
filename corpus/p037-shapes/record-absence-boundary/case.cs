// BOUNDARY (not closed by A2.2): methods that get NO functions[] record, so no
// sidecar can ride on them. Closing this needs a new record (a MOS change) or a
// new sidecar carrier (an OwnIR layout change): a case-5 decision under
// docs/notes/p037-formal-kernel.md §10.1, escalated with the measurement in
// docs/notes/p037-a2.2-call-facts.md §3. This shape pins today's absence so a
// change to it is visible, never silent.
using System;
using System.IO;

class Helper
{
    public void Close(Stream s, bool keep)
    {
        if (!keep)
        {
            s.Dispose();
        }
    }
}

class BoundaryBase
{
    protected BoundaryBase(Stream s, bool keep)
    {
        if (!keep)
        {
            s.Dispose();
        }
    }
}

class EmptyBodyDerived : BoundaryBase
{
    public EmptyBodyDerived(Stream s, bool keep) : base(s, keep) { }
}

static class ShapeRecordAbsence
{
    static void Inner(Stream s, bool keep)
    {
        if (!keep)
        {
            s.Dispose();
        }
    }

    static void ExpressionBodied(Stream s, bool keep) => Inner(s, keep);

    static void AllEscaped(string path, Helper? h)
    {
        var s = File.OpenRead(path);
        h?.Close(s, true);
    }
}
