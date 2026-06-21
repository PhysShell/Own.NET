using System;
using System.IO;

// A TRANSITIVE inter-procedural use-after-handoff: the stream is handed to `Consume`, which
// does NOT dispose it directly -- it FORWARDS it to `Inner`, which owns and closes it. So
// `Consume` consumes its parameter *transitively* (one hop further down the chain), and the
// caller's later read is a use-after-handoff. The consume signal travels through the
// forwarding chain: the extractor follows `Consume -> Inner -> Dispose` and models `Consume(s)`
// as a release of the argument at the call site, so a use after it trips OWN002. Unlike
// `ownership-handoff-use` (the callee disposes the param itself), here the callee only forwards.
static class HandoffUseTransitive
{
    // Direct consumer: owns and closes the stream.
    static void Inner(Stream s)
    {
        s.CopyTo(Stream.Null);
        s.Dispose();                    // Inner owns and closes it
    }

    // Transitive consumer: it does NOT close `sink` itself -- it forwards ownership to Inner.
    // `sink` is still consumed (its obligation is discharged via Inner), so a caller must not
    // touch the argument after the handoff.
    static void Consume(Stream sink)
    {
        Inner(sink);                    // ownership forwarded to the real consumer
    }

    // BUG: ownership moved into Consume (-> Inner, which disposed it), then the stream is read.
    static long Run(string path)
    {
        var s = File.OpenRead(path);
        Consume(s);                     // ownership moves to Consume -> Inner (disposed)
        return s.Length;                // use-after-handoff (s is disposed) -> OWN002
    }
}
