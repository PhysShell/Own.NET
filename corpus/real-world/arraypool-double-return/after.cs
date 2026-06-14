// AFTER (fixed): return exactly once, in finally.
using System.Buffers;

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
