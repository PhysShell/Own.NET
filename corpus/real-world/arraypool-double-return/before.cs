// BEFORE (buggy). Reduction of dotnet/runtime#33767 "Do not double-return
// arrays to ArrayPool": the same rented array is returned twice (here a Return
// on the success path AND a Return in finally). A double-return corrupts the
// pool — the array can later be rented out to two callers at once.
using System.Buffers;

static void Use(int n)
{
    int[] rented = ArrayPool<int>.Shared.Rent(n);
    try
    {
        Work(rented);
        ArrayPool<int>.Shared.Return(rented);   // returned here ...
    }
    finally
    {
        ArrayPool<int>.Shared.Return(rented);   // <-- ... and again here (double)
    }
}
