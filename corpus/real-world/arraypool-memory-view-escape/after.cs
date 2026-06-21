// FIX: copy the data OUT of the pooled buffer and return the COPY — no view of the recycled buffer
// escapes. Same try/finally cleanup, but nothing borrowed leaves the method, so it stays SILENT
// (the no-false-positive arm).
using System;
using System.Buffers;

static class PoolMemoryViewEscape
{
    static byte[] Render(int n)
    {
        byte[] buf = ArrayPool<byte>.Shared.Rent(n);
        try
        {
            return buf.AsSpan(0, n).ToArray();          // copy OUT -> a fresh array escapes, not a view
        }
        finally
        {
            ArrayPool<byte>.Shared.Return(buf);
        }
    }
}
