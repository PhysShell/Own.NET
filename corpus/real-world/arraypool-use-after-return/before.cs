// BEFORE (buggy). Reduction of the classic ArrayPool use-after-return bug seen
// across dotnet/runtime's buffer-pooling code (e.g. the BigInteger division
// path): a rented buffer is returned to the pool, then a slice of it is still
// read while building the result. Representative of the pattern, not verbatim
// from one PR.
using System.Buffers;

static int[] Divide(int dividend, int divisor)
{
    int[] quotient = ArrayPool<int>.Shared.Rent(Size(dividend));
    Compute(quotient, dividend, divisor);
    ArrayPool<int>.Shared.Return(quotient);   // <-- returned to the pool here ...
    return BuildResult(quotient);             // <-- ... but still read here (UAF)
}
