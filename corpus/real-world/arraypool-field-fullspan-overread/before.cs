// BEFORE (buggy). The FIELD twin of the ArrayPool "full-length view over-read"
// bug (P-007 POOL005). A pooled array is rented into a FIELD — `_buf =
// ArrayPool<T>.Shared.Rent(n)` — so the oversized buffer (`Length >= n`) outlives
// the method that filled it. A LATER member then takes a FULL-length view of the
// field (`_buf.AsSpan()`, no length bound) and reads through it, so the `n` valid
// bytes are processed together with the stale `[n, Length)` tail a *previous*
// renter left behind: a wrong-length read and an information disclosure. The
// per-method flow pass only tracks LOCAL rents, so this field-backed over-read is
// out of its reach; the field pass catches it. The fix is a bounded view,
// `_buf.AsSpan(0, _n)` (see after.cs). Representative of the pattern (a pooled
// scratch field viewed full-length on flush/serialize), not verbatim from one PR.
using System;
using System.Buffers;

sealed class FieldPoolFramer : IDisposable
{
    private byte[] _buf;
    private int _n;

    public void Capture(int n)
    {
        _n = n;
        _buf = ArrayPool<byte>.Shared.Rent(n);   // pooled buffer stored in a FIELD (Length >= n)
        Fill(_buf, n);                            // valid payload is _buf[0..n]
    }

    public byte[] Flush()
    {
        return _buf.AsSpan().ToArray();   // <-- BUG: full-length view of the pooled FIELD,
                                          //     n payload bytes + the stale [n, Length) tail
    }

    public void Dispose() => ArrayPool<byte>.Shared.Return(_buf);   // class-wide Return: no leak

    static void Fill(byte[] b, int n) { for (int i = 0; i < n; i++) b[i] = (byte)i; }
}
