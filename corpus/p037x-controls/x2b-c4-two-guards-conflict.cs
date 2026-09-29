// P-037-X Stage 2b hostile control X2B-C4: one parameter whose release is governed by TWO
// distinct eligible guard literals on two paths. R4 seeds G-S1's `Conflict` -> Uncond (the
// honest join, `may`): a caller passing constants gets plain + OWN051; NEVER consume.
using System.IO;

static class X2bC4
{
    static void Two(Stream s, bool a, bool b)
    {
        if (a)
        {
            s.Dispose();
            return;
        }
        if (b)
        {
            s.Dispose();
        }
    }

    static void Caller(string path)
    {
        var r = File.OpenRead(path);
        Two(r, true, false);
    }
}
