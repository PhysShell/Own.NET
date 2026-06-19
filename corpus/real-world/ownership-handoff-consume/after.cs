using System;
using System.IO;

static class Archiver
{
    public static void Archive(Stream source)
    {
        source.CopyTo(Stream.Null);
        source.Dispose();                  // Archive owns and closes it
    }

    // FIX (leak): dispose what we own. `using` discharges it on every path.
    static void Leak(string path)
    {
        using var s = File.OpenRead(path);
        Console.WriteLine(s.Length);
    }

    // FIX (use-after-handoff): read everything we need BEFORE handing ownership
    // off, then never touch the stream again.
    static void Run(string path)
    {
        var s = File.OpenRead(path);
        Console.WriteLine(s.Length);
        Archive(s);                        // move ownership last
    }

    // Unchanged: this handoff was already correct.
    static void RunOk(string path)
    {
        var s = File.OpenRead(path);
        Archive(s);
    }
}
