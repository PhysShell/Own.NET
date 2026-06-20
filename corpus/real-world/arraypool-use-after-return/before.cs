// BEFORE (buggy). Reduction of the classic ArrayPool use-after-return bug seen
// across dotnet/runtime's buffer-pooling code (e.g. the BigInteger division
// path): a rented buffer is returned to the pool, then a slice of it is still
// read while building the result. Representative of the pattern, not verbatim
// from one PR.
//
// Wrapped in a class so the extractor's per-class flow pass visits it; helpers
// stubbed so the reduction is self-contained.
using System.Buffers;

static class PoolUseAfterReturn
{
    static int[] Divide(int dividend, int divisor)
    {
        int[] quotient = ArrayPool<int>.Shared.Rent(Size(dividend));
        Compute(quotient, dividend, divisor);
        ArrayPool<int>.Shared.Return(quotient);   // <-- returned to the pool here ...
        return BuildResult(quotient);             // <-- ... but still read here (UAF)
    }

    static int Size(int n) => n;
    static void Compute(int[] buffer, int a, int b) { }
    // Returns a distinct copy (mirrors after.cs); the BUG here is reading `buffer`
    // in the return *after* it was returned to the pool — a use-after-return.
    static int[] BuildResult(int[] buffer) => (int[])buffer.Clone();
}
