// P-037-X Stage 2d hostile control X2D-C3: two forwards to RECORD-CARRYING callees on one path.
// R6 does not apply (both callees have coordinates): NO_GUARDED_EVIDENCE(multi_action) stays,
// fail-closed; the caller keeps the legacy `no` (uses) and is clean. (The first realization used
// callees whose bodies lowered to no op and so carried no record, which made R6 apply instead;
// re-realized before the recorded measurement, as the frozen shape says.)
using System.IO;

static class X2dC3
{
    static void Peek(Stream s)
    {
        s.ReadByte();
    }

    static void Peek2(Stream s)
    {
        s.ReadByte();
    }

    static void Two(Stream p)
    {
        Peek(p);
        Peek2(p);
    }

    static void Caller(string path)
    {
        var r = File.OpenRead(path);
        Two(r);
        r.Dispose();
    }
}
