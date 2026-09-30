// resource-effects Stage 1 compositional control H6: a first-party wrapper around the oracle factory
// (MakeLinked) and its curated-table twin H6b (OpenLog around File.OpenRead). Truth: both callers leak
// the wrapper's result (OWN001). Whether the wrapper gets a fresh summary is the pre-registered
// question: the bare-return rule (freshFactory) is gated on `new`ed candidates, so a factory-minted
// local returned bare may escape instead — the same residue for the key and for the production table.
using System.IO;
using System.Threading;

static class H6
{
    static CancellationTokenSource MakeLinked(CancellationToken t)
    {
        var cts = CancellationTokenSource.CreateLinkedTokenSource(t);
        return cts;
    }

    static void Run(CancellationToken t)
    {
        var c = MakeLinked(t);
        c.Cancel();
    }

    static FileStream OpenLog(string path)
    {
        var f = File.OpenRead(path);
        return f;
    }

    static void RunFile(string path)
    {
        var f = OpenLog(path);
        f.ReadByte();
    }
}
