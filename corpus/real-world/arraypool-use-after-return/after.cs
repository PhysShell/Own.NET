// AFTER (fixed): consume the buffer BEFORE returning it to the pool.
using System.Buffers;

static int[] Divide(int dividend, int divisor)
{
    int[] quotient = ArrayPool<int>.Shared.Rent(Size(dividend));
    Compute(quotient, dividend, divisor);
    int[] result = BuildResult(quotient);     // consume first ...
    ArrayPool<int>.Shared.Return(quotient);   // ... then return
    return result;
}
