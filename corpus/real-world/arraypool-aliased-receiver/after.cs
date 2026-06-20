// AFTER (fixed): return exactly once, in finally — through the same aliased receiver.
// (Wrapped in a class so the extractor's per-class flow pass visits it; Work stubbed.)
using System.Buffers;

static class PoolAliasedReceiver
{
    static void Use(int n)
    {
        ArrayPool<int> p = ArrayPool<int>.Shared;
        int[] rented = p.Rent(n);
        try
        {
            Work(rented);
        }
        finally
        {
            p.Return(rented);   // returned exactly once
        }
    }

    static void Work(int[] buffer) { }
}
