// AFTER (fixed): consume the buffer BEFORE returning it to the pool. (Wrapped in
// a class so the extractor's per-class flow pass visits it; helpers stubbed.)
using System.Buffers;

static class PoolUseAfterReturn
{
    static int[] Divide(int dividend, int divisor)
    {
        int[] quotient = ArrayPool<int>.Shared.Rent(Size(dividend));
        Compute(quotient, dividend, divisor);
        int[] result = BuildResult(quotient);     // consume first ...
        ArrayPool<int>.Shared.Return(quotient);   // ... then return
        return result;
    }

    static int Size(int n) => n;
    static void Compute(int[] buffer, int a, int b) { }
    static int[] BuildResult(int[] buffer) => buffer;
}
