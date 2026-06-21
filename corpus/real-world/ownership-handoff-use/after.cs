using System;
using System.IO;

// FIX: read everything we need BEFORE handing ownership off, then never touch the stream.
static class HandoffUse
{
    public static void Consume(Stream sink)
    {
        sink.CopyTo(Stream.Null);
        sink.Dispose();
    }

    static long Run(string path)
    {
        var s = File.OpenRead(path);
        long len = s.Length;            // read first ...
        Consume(s);                     // ... then move ownership last
        return len;
    }
}
