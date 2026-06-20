// AFTER (fixed): return exactly once, in finally. (Wrapped in a class so the
// extractor's per-class flow pass visits it; helper stubbed for self-containment.)
using System.Buffers;

static class PoolDoubleReturn
{
    static void Use(int n)
    {
        int[] rented = ArrayPool<int>.Shared.Rent(n);
        try
        {
            Work(rented);
        }
        finally
        {
            ArrayPool<int>.Shared.Return(rented);
        }
    }

    static void Work(int[] buffer) { }
}
