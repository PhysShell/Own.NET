// BEFORE (buggy). The "view STORED INTO A FIELD" twin of the ArrayPool
// full-length view over-read (P-007 POOL005; see `arraypool-field-fullspan-overread`
// for the inline-read twin). A pooled array is oversized — `ArrayPool<T>.Shared.Rent(n)`
// returns `Length >= n` — so a FULL-length view of it reaches past the logical
// length `n` into the stale `[n, Length)` tail a previous renter left behind.
//
// Here the full-length view is not read inline; it is captured into ANOTHER field
// (`_view = _buf.AsMemory()`, `_metaView = _meta.AsMemory()`) in one member and read
// through in a LATER member (`Flush`/`FlushMeta`). Whoever reads the stored view
// processes the `n` valid bytes together with that stale tail: a wrong-length read
// and an information disclosure. `Span<T>` is a ref struct and cannot be a field, so
// the field-stored view is a `Memory<T>` / `ReadOnlyMemory<T>` — the extractor's
// POOL005 field pass fires on the full-length view EXPRESSION at the store, so the
// bug is caught where the unbounded view is materialized. The fix is a bounded view,
// `_buf.AsMemory(0, _n)` (see after.cs). Representative of the pattern (a pooled
// scratch field whose whole-array view is cached for later flush/serialize), not
// verbatim from one PR.
using System;
using System.Buffers;

sealed class FieldViewFramer : IDisposable
{
    private byte[] _buf;
    private Memory<byte> _view;              // a FULL-length view stored into a field
    private int _n;

    // a SECOND pooled buffer, rented in the FIELD INITIALIZER, whose whole-array view
    // is cached into a ReadOnlyMemory field below.
    private readonly byte[] _meta = ArrayPool<byte>.Shared.Rent(64);   // Length >= 64
    private ReadOnlyMemory<byte> _metaView;

    public void Capture(int n)
    {
        _n = n;
        _buf = ArrayPool<byte>.Shared.Rent(n);   // pooled buffer stored in a FIELD (Length >= n)
        Fill(_buf, n);                            // valid payload is _buf[0..n]
        _view = _buf.AsMemory();                  // <-- BUG: full-length view cached into a field
        _metaView = _meta.AsMemory();             // <-- BUG: full-length view into a ReadOnlyMemory field
    }

    public byte[] Flush() => _view.ToArray();        // reads the cached full view: n bytes + stale [n, Length) tail
    public byte[] FlushMeta() => _metaView.ToArray();

    public void Dispose()
    {
        if (_buf is not null)                    // null until Capture; Return(null) would throw
            ArrayPool<byte>.Shared.Return(_buf); // class-wide Return: no leak
        ArrayPool<byte>.Shared.Return(_meta);    // initializer-rented, never null
    }

    static void Fill(byte[] b, int n) { for (int i = 0; i < n; i++) b[i] = (byte)i; }
}
