// BEFORE (buggy). The FIELD twin of the ArrayPool "full-length view over-read"
// bug (P-007 POOL005). A pooled array is rented into a FIELD — by assignment
// (`_buf = ArrayPool<T>.Shared.Rent(n)`) OR a field initializer (`byte[] _meta =
// ArrayPool<T>.Shared.Rent(MetaCap)`) — so the oversized buffer (`Length >= n`)
// outlives the method that filled it. A LATER member then takes a FULL-length
// view of the field and reads through it, so the `n` valid bytes are processed
// together with the stale `[n, Length)` tail a *previous* renter left behind: a
// wrong-length read and an information disclosure. Two view spellings are pinned:
// the bare `_buf.AsSpan()` over the assignment-rented field, and the `.Length`
// spelling `_meta.AsSpan(0, _meta.Length)` over the initializer-rented field. The
// per-method flow pass only tracks LOCAL rents, so these field-backed over-reads
// are out of its reach; the field pass catches them. The fix is a bounded view,
// `_buf.AsSpan(0, _n)` (see after.cs). Representative of the pattern (a pooled
// scratch field viewed full-length on flush/serialize), not verbatim from one PR.
using System;
using System.Buffers;

sealed class FieldPoolFramer : IDisposable
{
    private byte[] _buf;
    private int _n;

    // a SECOND pooled buffer, rented in the FIELD INITIALIZER (not an assignment) and viewed full-length
    // below via the `.Length` spelling — exercises the field-initializer rent + the IsFieldLengthOf branch.
    private const int MetaCap = 64;
    private readonly byte[] _meta = ArrayPool<byte>.Shared.Rent(MetaCap);   // Length >= MetaCap
    private int _metaLen;

    public void Capture(int n)
    {
        _n = n;
        _buf = ArrayPool<byte>.Shared.Rent(n);   // pooled buffer stored in a FIELD (Length >= n)
        Fill(_buf, n);                            // valid payload is _buf[0..n]
        _metaLen = 8;
        Fill(_meta, _metaLen);                    // valid payload is _meta[0.._metaLen]
    }

    public byte[] Flush()
    {
        return _buf.AsSpan().ToArray();   // <-- BUG: full-length view of the pooled FIELD,
                                          //     n payload bytes + the stale [n, Length) tail
    }

    public byte[] FlushMeta()
    {
        return _meta.AsSpan(0, _meta.Length).ToArray();   // <-- BUG (`.Length` spelling): the WHOLE
                                                          //     oversized array, past _metaLen
    }

    public void Dispose()
    {
        ArrayPool<byte>.Shared.Return(_buf);     // class-wide Return: no leak
        ArrayPool<byte>.Shared.Return(_meta);
    }

    static void Fill(byte[] b, int n) { for (int i = 0; i < n; i++) b[i] = (byte)i; }
}
