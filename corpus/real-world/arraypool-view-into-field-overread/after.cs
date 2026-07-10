// AFTER (fixed). The cached field view is bounded to the LOGICAL length the buffer
// was rented for (`_buf.AsMemory(0, _n)`, `_meta.AsMemory(0, _metaLen)`), so it spans
// only the valid `[0, n)` bytes and never the stale `[n, Length)` tail — no over-read.
// A bounded view is not a full-length view, so the extractor's POOL005 field pass
// returns null on it and this file is silent (the specificity half of the corpus
// gate: the real fix raises nothing). The buffers are still `Return`ed in `Dispose`.
using System;
using System.Buffers;

sealed class FieldViewFramer : IDisposable
{
    private byte[] _buf;
    private Memory<byte> _view;
    private int _n;

    private readonly byte[] _meta = ArrayPool<byte>.Shared.Rent(64);
    private ReadOnlyMemory<byte> _metaView;
    private int _metaLen;

    public void Capture(int n)
    {
        _n = n;
        _buf = ArrayPool<byte>.Shared.Rent(n);
        Fill(_buf, n);
        _view = _buf.AsMemory(0, _n);            // FIX: bounded to the logical length
        _metaLen = 8;
        Fill(_meta, _metaLen);                   // write the valid metadata bytes first...
        _metaView = _meta.AsMemory(0, _metaLen); // ...then expose only those (bounded — no stale tail)
    }

    public byte[] Flush() => _view.ToArray();
    public byte[] FlushMeta() => _metaView.ToArray();

    public void Dispose()
    {
        if (_buf is not null)
            ArrayPool<byte>.Shared.Return(_buf);
        ArrayPool<byte>.Shared.Return(_meta);
    }

    static void Fill(byte[] b, int n) { for (int i = 0; i < n; i++) b[i] = (byte)i; }
}
