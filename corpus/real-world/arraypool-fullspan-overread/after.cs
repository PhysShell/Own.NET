// AFTER (fixed). Every view is BOUNDED to the logical length — `buf.AsSpan(0, n)` —
// so only the `n` valid payload bytes are read; the oversized `[n, Length)` tail is
// never touched. No unbounded full view remains in either spelling (expression or
// initializer), so the extractor emits no `overspan` fact and the checker is silent.
using System;
using System.Buffers;

static class PoolFullSpanOverread
{
    static byte[] Frame(int n)
    {
        byte[] buf = ArrayPool<byte>.Shared.Rent(n);
        Fill(buf, n);
        Emit(buf.AsSpan(0, n));                    // bounded view: only the logical [0, n)
        byte[] copy = buf.AsSpan(0, n).ToArray();  // bounded copy: only the logical [0, n)
        ArrayPool<byte>.Shared.Return(buf);
        return copy;
    }

    static void Fill(byte[] b, int n) { for (int i = 0; i < n; i++) b[i] = (byte)i; }
    static void Emit(ReadOnlySpan<byte> data) { }
}
