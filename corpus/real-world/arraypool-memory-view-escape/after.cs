// FIX: copy the data OUT of the pooled buffer before returning it, and hand the caller the copy —
// no view of the recycled buffer escapes the method. Same Return, but nothing borrowed leaves it,
// so the case must stay SILENT (the no-false-positive arm).
using System;
using System.Buffers;

static class PoolMemoryViewEscape
{
    static byte[] Render(int n)
    {
        byte[] buf = ArrayPool<byte>.Shared.Rent(n);
        byte[] copy = buf.AsSpan(0, n).ToArray();    // copy OUT before returning the buffer
        ArrayPool<byte>.Shared.Return(buf);
        return copy;                                 // a fresh copy escapes, not a view -> silent
    }
}
