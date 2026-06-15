using System;
using System.Buffers;

namespace PoolApp;

public static class Hasher
{
    // Rents a pooled buffer and never returns it: pool leak / GC pressure. The
    // core reports OWN001 [resource: pooled buffer] at the Rent.
    public static int LeakyHash(int n)
    {
        var leaky = ArrayPool<byte>.Shared.Rent(n);
        return leaky.Length;   // never Return(leaky) => leak
    }

    // Rents and returns in a finally — not flagged.
    public static int CleanHash(int n)
    {
        var ok = ArrayPool<byte>.Shared.Rent(n);
        try { return ok.Length; }
        finally { ArrayPool<byte>.Shared.Return(ok); }
    }
}
