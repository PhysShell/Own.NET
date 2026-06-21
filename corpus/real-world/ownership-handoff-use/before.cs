using System;
using System.IO;

// A pure inter-procedural use-after-handoff (no leak arm): a stream is handed to a
// consumer that takes OWNERSHIP (reads it, then disposes it), and the caller then touches
// the stream again. Unlike ownership-handoff-consume there is no leak arm -- the handoff
// itself is correct, so the ONLY bug is the use AFTER ownership moved. Common shape:
// serialize/compress into a stream, hand it to a sink that owns it, then accidentally read
// it once more (an ObjectDisposedException at runtime).
static class HandoffUse
{
    // Consumer: takes ownership of `sink` and closes it. `sink` is `consume Stream`.
    public static void Consume(Stream sink)
    {
        sink.CopyTo(Stream.Null);
        sink.Dispose();                 // Consume owns and closes it
    }

    // BUG: ownership moved into Consume (which disposed it), then the stream is read. -> OWN002
    static long Run(string path)
    {
        var s = File.OpenRead(path);
        Consume(s);                     // ownership moves to Consume
        return s.Length;                // use-after-handoff (s is disposed) -> OWN002
    }
}
