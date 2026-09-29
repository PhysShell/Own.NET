// P-037-X Stage 2b hostile control X2B-C2: a sidecar-less record whose body has a `while`
// around a use. No eligible guard, no relevant call: no sidecar. R1 must keep
// NO_GUARDED_EVIDENCE(missing_sidecar) because the body carries a structural op.
using System.IO;

static class X2bC2
{
    static void Loop(Stream s, int n)
    {
        while (n-- > 0)
        {
            s.ReadByte();
        }
    }

    static void Caller(string path)
    {
        var r = File.OpenRead(path);
        Loop(r, 3);
        r.Dispose();
    }
}
