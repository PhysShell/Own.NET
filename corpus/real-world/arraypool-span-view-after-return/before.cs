// BEFORE (buggy). A Span VIEW of a pooled buffer is written THROUGH after the buffer was returned
// to the pool. `buf.AsSpan(..)` borrows the buffer's memory into a `Span<byte>` local; once
// `Return(buf)` recycles the array the pool may hand it to another caller, so writing through the
// view now corrupts someone else's data — a silent, nasty aliasing bug. The view is a ref-struct
// BORROW: a use of it after the owner's release is a use-after-return. Unlike
// `arraypool-use-after-return` (the array itself is read after return), here the read goes through
// a STORED Span view, which the flat pass misses — the borrow has to be resolved to its owner.
//
// Wrapped in a class so the extractor's per-class flow pass visits it.
using System;
using System.Buffers;

static class PoolSpanViewAfterReturn
{
    static void Scramble(int n)
    {
        byte[] buf = ArrayPool<byte>.Shared.Rent(n);
        Span<byte> view = buf.AsSpan(0, n);          // view BORROWS buf
        ArrayPool<byte>.Shared.Return(buf);          // buf goes back to the pool (recycled) ...
        view[0] = 42;                                // ... but written through here (use-after-return)
    }
}
