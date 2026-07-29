using System;
using System.Buffers;

namespace Own.Corpus.Mini;

// A pooled buffer rented and never returned: POOL001, OWN001
// [resource: pooled buffer]. A fourth resource kind in the corpus, so the pattern
// projection covers more than the event/disposable pair.
public sealed class PooledLeak
{
    public int Leaks(int n)
    {
        var buffer = ArrayPool<byte>.Shared.Rent(n);
        return buffer.Length;
    }

    // Rented and returned in a finally -> released on every path -> silent.
    public int Returned(int n)
    {
        var buffer = ArrayPool<byte>.Shared.Rent(n);
        try
        {
            return buffer.Length;
        }
        finally
        {
            ArrayPool<byte>.Shared.Return(buffer);
        }
    }
}
