// CLASS-3 SHAPE (class 4, P-037 G-T2b class 3 — the formal kernel's F1 pin,
// docs/notes/p037-formal-kernel.md §4). A guarded local release with an
// UNRESOLVED forward on the other branch: today's release priority emits
// [dispose, borrow] = may and never processes the forward; the guarded
// derivation says (must, unknown), collapse unknown. Same verdict under
// INF-A1 (plain + OWN051 for an unknown guard), so this fixture pins the
// VERDICT only; the value-level pin (unknown, never "repaired" to may) is the
// kernel test `k11_finding_release_priority_drops_an_unresolved_forward` and,
// after A1, the summary-dump golden.
// Required at --severity warning, today and after A1: NO findings.
// MEASURED TODAY: 0 findings (plain + OWN051 for the unknown guard).
using System;

public sealed class Res : IDisposable
{
    public void Dispose() { }
}

public interface ISink
{
    void Take(Res p);           // unresolved: an interface target, no summary
}

public static class Guarded
{
    public static void M(Res p, bool g, ISink sink)
    {
        if (g)
        {
            p.Dispose();
        }
        else
        {
            sink.Take(p);       // the forward today's release priority drops
        }
    }

    public static void Use(bool flag, ISink sink)
    {
        var r = new Res();
        M(r, flag, sink);       // unknown guard: plain + OWN051, never consume
    }
}
