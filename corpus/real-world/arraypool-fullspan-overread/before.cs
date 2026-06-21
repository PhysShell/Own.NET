// BEFORE (buggy). Reduction of the ArrayPool "full-length view over-read" bug
// (P-007 POOL005). A rented array is OVERSIZED: `ArrayPool<T>.Shared.Rent(n)`
// returns an array of `Length >= n`, not exactly `n`. Here the code fills the
// first `n` bytes, then takes a FULL-length view — `buf.AsSpan()` with no length —
// so the `n` valid bytes are read together with the stale `[n, Length)` tail a
// *previous* renter left behind: a wrong-length read and an information disclosure.
// Both spellings are caught: the view used in an EXPRESSION (`Emit(buf.AsSpan())`)
// and the view in a local-declaration INITIALIZER (`var copy = buf.AsSpan()...`).
// The fix is a bounded view, `buf.AsSpan(0, n)` (see after.cs). Representative of
// the pattern (pooled-buffer over-read/over-copy in tensor and serialization code),
// not verbatim from one PR.
//
// Wrapped in a class so the extractor's per-class flow pass visits it; helpers
// stubbed so the reduction is self-contained.
using System;
using System.Buffers;

static class PoolFullSpanOverread
{
    static byte[] Frame(int n)
    {
        byte[] buf = ArrayPool<byte>.Shared.Rent(n);
        Fill(buf, n);                          // valid payload is buf[0..n]
        Emit(buf.AsSpan());                    // <-- BUG (expression): the WHOLE oversized array,
                                               //     n payload bytes + the stale [n, Length) tail
        byte[] copy = buf.AsSpan().ToArray();  // <-- BUG (initializer): the same over-read in a local
        ArrayPool<byte>.Shared.Return(buf);
        return copy;
    }

    static void Fill(byte[] b, int n) { for (int i = 0; i < n; i++) b[i] = (byte)i; }
    static void Emit(ReadOnlySpan<byte> data) { }
}
