// AFTER (fixed). Finish all work through the Span view BEFORE returning the buffer to the pool, so
// the borrow's lifetime ends before the owner is recycled and nothing aliases freed memory. Same
// view, correct order — the case must stay SILENT (the no-false-positive arm).
using System;
using System.Buffers;

static class PoolSpanViewAfterReturn
{
    static void Scramble(int n)
    {
        byte[] buf = ArrayPool<byte>.Shared.Rent(n);
        Span<byte> view = buf.AsSpan(0, n);          // view BORROWS buf
        view[0] = 42;                                // written through the view BEFORE return
        ArrayPool<byte>.Shared.Return(buf);          // returned only after the borrow is done -> silent
    }
}
