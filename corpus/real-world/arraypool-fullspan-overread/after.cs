// AFTER (fixed). The view is BOUNDED to the logical length — `buf.AsSpan(0, n)` —
// so only the `n` valid payload bytes are handed off; the oversized `[n, Length)`
// tail is never read. The unbounded full view is gone, so the extractor emits no
// `overspan` fact and the checker is silent.
using System;
using System.Buffers;

static class PoolFullSpanOverread
{
    static void Frame(int n)
    {
        byte[] buf = ArrayPool<byte>.Shared.Rent(n);
        Fill(buf, n);
        Emit(buf.AsSpan(0, n));       // <-- bounded view: only the logical [0, n)
        ArrayPool<byte>.Shared.Return(buf);
    }

    static void Fill(byte[] b, int n) { for (int i = 0; i < n; i++) b[i] = (byte)i; }
    static void Emit(ReadOnlySpan<byte> data) { }
}
