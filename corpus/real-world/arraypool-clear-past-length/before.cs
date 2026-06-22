// BEFORE (buggy). POOL005, the `.Length` spelling of the over-read / over-clear.
// A rented array is OVERSIZED: `ArrayPool<T>.Shared.Rent(n)` returns an array of
// `Length >= n`. This code uses `buf.Length` — the oversized backing length — as
// the operative length instead of the rented `n`: `buf.AsSpan(0, buf.Length)`
// hands off the stale `[n, Length)` tail (a previous renter's bytes), and
// `Array.Clear(buf, 0, buf.Length)` clears past `n` into that tail. The fix is to
// bound by the logical length `n` (`buf.AsSpan(0, n)`, `Array.Clear(buf, 0, n)`,
// see after.cs). Representative of the pattern, not verbatim from one PR.
//
// Wrapped in a class so the extractor's per-class flow pass visits it; helpers
// stubbed so the reduction is self-contained.
using System;
using System.Buffers;

static class PoolClearPastLength
{
    static void Roundtrip(int n)
    {
        byte[] buf = ArrayPool<byte>.Shared.Rent(n);
        Fill(buf, n);                       // valid payload is buf[0..n]
        Emit(buf.AsSpan(0, buf.Length));    // <-- BUG: length is buf.Length, not n -> stale tail
        Array.Clear(buf, 0, buf.Length);    // <-- BUG: clears past n into the pooled tail
        ArrayPool<byte>.Shared.Return(buf);
    }

    static void Fill(byte[] b, int n) { for (int i = 0; i < n; i++) b[i] = (byte)i; }
    static void Emit(ReadOnlySpan<byte> data) { }
}
