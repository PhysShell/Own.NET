// BEFORE (buggy). Reduction of the ArrayPool "full-length view over-read" bug
// (P-007 POOL005). A rented array is OVERSIZED: `ArrayPool<T>.Shared.Rent(n)`
// returns an array of `Length >= n`, not exactly `n`. Here the code fills the
// first `n` bytes, then hands off a FULL-length view — `buf.AsSpan()` with no
// length — so the consumer reads the `n` valid bytes PLUS the stale `[n, Length)`
// tail a *previous* renter left behind: a wrong-length read and an information
// disclosure. The fix is a bounded view, `buf.AsSpan(0, n)` (see after.cs).
// Representative of the pattern (pooled-buffer over-read/over-copy in tensor and
// serialization code), not verbatim from one PR.
//
// Wrapped in a class so the extractor's per-class flow pass visits it; helpers
// stubbed so the reduction is self-contained.
using System;
using System.Buffers;

static class PoolFullSpanOverread
{
    static void Frame(int n)
    {
        byte[] buf = ArrayPool<byte>.Shared.Rent(n);
        Fill(buf, n);                 // valid payload is buf[0..n]
        Emit(buf.AsSpan());           // <-- BUG: the WHOLE oversized array, not buf.AsSpan(0, n):
                                      //     n payload bytes + the stale [n, Length) tail
        ArrayPool<byte>.Shared.Return(buf);
    }

    static void Fill(byte[] b, int n) { for (int i = 0; i < n; i++) b[i] = (byte)i; }
    static void Emit(ReadOnlySpan<byte> data) { }
}
