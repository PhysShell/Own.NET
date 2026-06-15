using System;
using System.IO;

namespace Streams;

public static class Loader
{
    // A MemoryStream created but never disposed and not in a `using`: leak. The
    // core reports OWN001 [resource: disposable] at the declaration.
    public static long Leaky()
    {
        var leaky = new MemoryStream();
        leaky.WriteByte(1);
        return leaky.Length;   // never disposed => leak
    }

    // `using` guarantees disposal — not flagged.
    public static long Guarded()
    {
        using var guarded = new MemoryStream();
        guarded.WriteByte(1);
        return guarded.Length;
    }

    // Ownership transferred to the caller (returned) — not flagged.
    public static Stream Transfer()
    {
        var moved = new MemoryStream();
        return moved;
    }
}
