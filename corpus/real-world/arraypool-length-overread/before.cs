// BEFORE (buggy). POOL005, the `.Length` spelling of the over-read. A rented array
// is OVERSIZED: `ArrayPool<T>.Shared.Rent(n)` returns an array of `Length >= n`.
// Viewing it with `buf.Length` — the oversized backing length — as the bound,
// `buf.AsSpan(0, buf.Length)`, spans the WHOLE array, so a consumer reads the `n`
// valid bytes PLUS the stale `[n, Length)` tail a previous renter left: a wrong-
// length read and an information disclosure. The fix is `buf.AsSpan(0, n)` (after.cs).
//
// Note: an over-CLEAR like `Array.Clear(buf, 0, buf.Length)` is deliberately NOT
// flagged — it only overwrites the pooled tail with zeros (a safe clear-before-Return
// idiom) and exposes nothing. The bug is READING/COPYING the tail, which the view
// spelling does.
//
// Wrapped in a class so the extractor's per-class flow pass visits it; helpers stubbed.
using System;
using System.Buffers;

static class PoolLengthOverread
{
    static void Frame(int n)
    {
        byte[] buf = ArrayPool<byte>.Shared.Rent(n);
        Fill(buf, n);                       // valid payload is buf[0..n]
        Emit(buf.AsSpan(0, buf.Length));    // <-- BUG: length is buf.Length, not n -> reads the stale tail
        ArrayPool<byte>.Shared.Return(buf);
    }

    static void Fill(byte[] b, int n) { for (int i = 0; i < n; i++) b[i] = (byte)i; }
    static void Emit(ReadOnlySpan<byte> data) { }
}
