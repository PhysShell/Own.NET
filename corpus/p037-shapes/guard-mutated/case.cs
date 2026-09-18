// The guard parameter is WRITTEN before the branch reads it, so its entry value
// no longer decides the branch. G-V4 fails closed: no eligible guard, therefore
// no guard metadata at all. Absence IS the fail-closed signal — the frontend
// never emits "stable": false, because an old producer, an unstable parameter,
// an unsupported predicate and unknown syntax must all degrade the same way.
using System.IO;

static class ShapeMutatedGuard
{
    static void Inner(Stream p, bool keep)
    {
        keep = !keep;
        if (!keep)
        {
            p.Dispose();
        }
    }

    static void Caller(string path)
    {
        var r = File.OpenRead(path);
        Inner(r, true);
        r.Dispose();
    }
}
