// BEFORE (buggy). Reduction of dotnet/runtime#33767 "Do not double-return
// arrays to ArrayPool": the same rented array is returned twice (here a Return
// on the success path AND a Return in finally). A double-return corrupts the
// pool — the array can later be rented out to two callers at once.
//
// Wrapped in a class so the extractor's per-class flow pass visits it (a
// file-scope method parses as a top-level local function, which the pass does not
// walk); the helper is stubbed so the reduction is self-contained.
using System.Buffers;

static class PoolDoubleReturn
{
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

    static void Work(int[] buffer) { }
}
