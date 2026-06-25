// AFTER (fixed). Every full-length view of a pooled field is BOUNDED to the logical
// length — `_buf.AsSpan(0, _n)` and `_meta.AsSpan(0, _metaLen)` — so only the valid
// payload bytes are read; the oversized `[len, Length)` tail is never touched. With
// no unbounded view (and no `.Length`-spelled view) over either field — the
// assignment-rented `_buf` or the initializer-rented `_meta` — the extractor emits
// no `overspan` fact and the checker is silent.
using System;
using System.Buffers;

sealed class FieldPoolFramer : IDisposable
{
    private byte[] _buf;
    private int _n;

    private const int MetaCap = 64;
    private readonly byte[] _meta = ArrayPool<byte>.Shared.Rent(MetaCap);
    private int _metaLen;

    public void Capture(int n)
    {
        _n = n;
        _buf = ArrayPool<byte>.Shared.Rent(n);
        Fill(_buf, n);
        _metaLen = 8;
        Fill(_meta, _metaLen);
    }

    public byte[] Flush()
    {
        return _buf.AsSpan(0, _n).ToArray();   // bounded view: only the logical [0, n)
    }

    public byte[] FlushMeta()
    {
        return _meta.AsSpan(0, _metaLen).ToArray();   // bounded view: only the logical [0, _metaLen)
    }

    public void Dispose()
    {
        if (_buf is not null)                    // null until Capture; Return(null) would throw
            ArrayPool<byte>.Shared.Return(_buf);
        ArrayPool<byte>.Shared.Return(_meta);    // initializer-rented, never null
    }

    static void Fill(byte[] b, int n) { for (int i = 0; i < n; i++) b[i] = (byte)i; }
}
