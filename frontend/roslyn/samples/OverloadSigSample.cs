using System.IO;

// Interprocedural stage 2 (spec/OwnIR.md §5.1) — per-overload signature keys.
//
// `Open` is OVERLOADED: the `(string)` overload is a fresh factory (constructs
// and returns a new FileStream), the `(FileStream, bool)` overload returns its
// own parameter (not fresh). Pre-stage-2 both merged into one name-keyed summary
// whose returns DISAGREE -> no fresh claim -> the dropped result in `Drop` leaked
// invisibly. With `sig` stamped on the `functions[]` records and the `call` op,
// the call resolves the `(string)` overload's own summary (`fresh`), so the
// dropped stream surfaces as OWN001 at the call site.

public static class SigOverloads
{
    public static FileStream Open(string path)
    {
        var opened = new FileStream(path, FileMode.Open);   // fresh factory
        return opened;
    }

    public static FileStream Open(FileStream existing, bool flush)
    {
        var probe = new MemoryStream();   // a tracked local, so this overload emits a record
        probe.Dispose();
        if (flush)
            existing.Flush();
        return existing;                  // returns a PARAMETER -> not fresh
    }

    public static void Drop(string path)
    {
        var dropped = Open(path);   // sig'd call -> the fresh overload's contract
        dropped.Flush();            // used but never disposed: OWN001 (the leak stage 2 restores)
    }
}
