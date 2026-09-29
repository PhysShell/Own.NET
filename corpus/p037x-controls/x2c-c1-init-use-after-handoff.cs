// P-037-X Stage 2c hostile control X2C-C1 (frozen in paper-eval/p037-max/stage2c-prereg-v1.json):
// an initializer-form call takes the handle AFTER a definite handoff of it. R5 makes the legacy
// body show that use, so the core reports a TRUE use-after-dispose (OWN002) on both engines —
// precision, not fabrication. Before R5 the use was invisible and the document was silent.
// The handle is a PARAMETER: a local handed to an initializer-form call escapes by the legacy
// rule ("a `var n = Consume(s)` initializer stays an escape rather than a false leak"), so it
// carries no record; parameters are the coordinates the guarded vocabulary reads anyway.
using System.IO;

static class X2cC1
{
    static void Take(Stream s)
    {
        s.Dispose();
    }

    static int Length(Stream s)
    {
        return (int)s.Length;
    }

    static int AfterHandoff(Stream r)
    {
        Take(r);
        var len = Length(r);
        return len;
    }
}
