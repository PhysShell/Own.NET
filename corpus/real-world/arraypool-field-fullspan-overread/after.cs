// AFTER (fixed). The full-length view of the pooled field is BOUNDED to the logical
// length — `_buf.AsSpan(0, _n)` — so only the `n` valid payload bytes are read; the
// oversized `[n, Length)` tail is never touched. With no unbounded view (and no
// `.Length`-spelled view) over the field, the extractor emits no `overspan` fact and
// the checker is silent.
using System;
using System.Buffers;

sealed class FieldPoolFramer : IDisposable
{
    private byte[] _buf;
    private int _n;

    public void Capture(int n)
    {
        _n = n;
        _buf = ArrayPool<byte>.Shared.Rent(n);
        Fill(_buf, n);
    }

    public byte[] Flush()
    {
        return _buf.AsSpan(0, _n).ToArray();   // bounded view: only the logical [0, n)
    }

    public void Dispose() => ArrayPool<byte>.Shared.Return(_buf);

    static void Fill(byte[] b, int n) { for (int i = 0; i < n; i++) b[i] = (byte)i; }
}
