// P-037-X Stage 2c hostile control X2C-C2: an initializer-form call takes the handle BEFORE its
// owner disposes it. Clean on both engines; `Keep`, whose only use of its parameter is the
// initializer-form call, summarizes Uncond(no) with the flag on (a use is not an action), so the
// owner's canonical `Keep(r)` is a borrow and its later dispose is fine. Mutant M1 (emitting the
// initializer use as a release) must turn this red: Keep would read `must`, the owner's dispose
// a fabricated OWN003.
using System.IO;

static class X2cC2
{
    static int Length(Stream s)
    {
        return (int)s.Length;
    }

    static void Keep(Stream s)
    {
        var len = Length(s);
        _ = len;
    }

    static void Owner(string path)
    {
        var r = File.OpenRead(path);
        Keep(r);
        r.Dispose();
    }
}
