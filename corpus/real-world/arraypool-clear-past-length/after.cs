// AFTER (fixed). Every length/count argument is bound to the logical length `n`,
// not the oversized `buf.Length`: `buf.AsSpan(0, n)` views only the valid payload
// and `Array.Clear(buf, 0, n)` clears only it. The `[n, Length)` tail is never
// touched, so the extractor emits no `overspan` fact and the checker is silent.
using System;
using System.Buffers;

static class PoolClearPastLength
{
    static void Roundtrip(int n)
    {
        byte[] buf = ArrayPool<byte>.Shared.Rent(n);
        Fill(buf, n);
        Emit(buf.AsSpan(0, n));    // bounded by the rented length n
        Array.Clear(buf, 0, n);    // clears only the logical [0, n)
        ArrayPool<byte>.Shared.Return(buf);
    }

    static void Fill(byte[] b, int n) { for (int i = 0; i < n; i++) b[i] = (byte)i; }
    static void Emit(ReadOnlySpan<byte> data) { }
}
