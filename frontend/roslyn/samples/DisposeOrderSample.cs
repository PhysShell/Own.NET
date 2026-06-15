using System;
using System.IO;

namespace DisposeOrder;

public static class Streams
{
    // Use after Dispose: touching the stream after disposing it (OWN002).
    public static void UseAfter()
    {
        var s = new MemoryStream();
        s.Dispose();
        s.WriteByte(1);   // use-after-dispose
    }

    // Double dispose: disposing the same stream twice (OWN003).
    public static void DoubleDispose()
    {
        var s = new MemoryStream();
        s.Dispose();
        s.Dispose();      // double dispose
    }
}
