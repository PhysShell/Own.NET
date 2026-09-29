// P-037-X Stage 2b hostile control X2B-C1 (frozen in paper-eval/p037-max/stage2b-prereg-v1.json):
// a sidecar-less record whose body has an `if` on a NON-parameter-bool condition around the
// release. A2.1 records no eligible guard (`n > 0` is not a truth/null predicate on a parameter)
// and no relevant call, so no sidecar rides; R1 must NOT read the absence as an empty sidecar:
// the body carries an `if`, so NO_GUARDED_EVIDENCE(missing_sidecar) stays and the caller keeps
// the legacy `may` (OWN051, never consume).
using System.IO;

static class X2bC1
{
    static void Leaf(Stream s, int n)
    {
        if (n > 0)
        {
            s.Dispose();
        }
    }

    static void Caller(string path)
    {
        var r = File.OpenRead(path);
        Leaf(r, 1);
    }
}
