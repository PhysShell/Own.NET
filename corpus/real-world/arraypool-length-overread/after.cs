// AFTER (fixed). The view is bound to the logical length `n` — `buf.AsSpan(0, n)` —
// so only the `n` valid payload bytes are read; the oversized `[n, Length)` tail is
// never touched. No `.Length`-spelled view remains, so the extractor emits no
// `overspan` fact and the checker is silent.
using System;
using System.Buffers;

static class PoolLengthOverread
{
    static void Frame(int n)
    {
        byte[] buf = ArrayPool<byte>.Shared.Rent(n);
        Fill(buf, n);
        Emit(buf.AsSpan(0, n));    // bounded by the rented length n
        ArrayPool<byte>.Shared.Return(buf);
    }

    static void Fill(byte[] b, int n) { for (int i = 0; i < n; i++) b[i] = (byte)i; }
    static void Emit(ReadOnlySpan<byte> data) { }
}
