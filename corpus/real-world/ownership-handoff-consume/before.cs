using System;
using System.IO;

// A consumer that takes OWNERSHIP of the stream: it copies the stream, then
// disposes it. Callers hand the stream over and must not touch it afterwards.
// In OwnLang terms `Archive`'s parameter is `consume Stream` -- the release
// obligation moves into Archive across the call.
static class Archiver
{
    public static void Archive(Stream source)
    {
        source.CopyTo(Stream.Null);
        source.Dispose();                  // Archive owns and closes it
    }

    // BUG (leak): the stream is neither disposed nor handed to a consumer, so
    // on the only path it leaks. -> OWN001
    static void Leak(string path)
    {
        var s = File.OpenRead(path);
        Console.WriteLine(s.Length);
    }

    // BUG (use-after-handoff): ownership moved into Archive (which disposed it),
    // then the stream is touched again. -> OWN002
    static void Run(string path)
    {
        var s = File.OpenRead(path);
        Archive(s);                        // ownership moves to Archive
        Console.WriteLine(s.Length);       // use-after-dispose through s
    }

    // OK: same handoff, but nothing touches the stream after it. Correctly not
    // a leak -- the obligation travelled to Archive.
    static void RunOk(string path)
    {
        var s = File.OpenRead(path);
        Archive(s);
    }
}
