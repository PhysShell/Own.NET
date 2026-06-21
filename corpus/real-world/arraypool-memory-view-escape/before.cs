// A Memory<T> VIEW of a pooled buffer ESCAPES the method — returned from inside a `try` whose
// `finally` returns the buffer to the pool (THE idiomatic ArrayPool cleanup). The `return view`
// expression is evaluated before the finally runs, but the caller receives the `Memory<byte>` only
// AFTER the finally has recycled the buffer — so the caller then reads/writes memory the pool has
// already handed to someone else (a silent cross-tenant corruption). Unlike a `Span` (a ref struct
// the compiler keeps inside the method), a `Memory<T>` CAN leave the method, so the borrow outlives
// its owner: a dangling escape past the finally.
//
// Wrapped in a class so the extractor's per-class flow pass visits it.
using System;
using System.Buffers;

static class PoolMemoryViewEscape
{
    static Memory<byte> Render(int n)
    {
        byte[] buf = ArrayPool<byte>.Shared.Rent(n);
        try
        {
            Memory<byte> view = buf.AsMemory(0, n);     // view BORROWS buf
            return view;                                // escapes -> caller gets it AFTER the finally
        }
        finally
        {
            ArrayPool<byte>.Shared.Return(buf);         // buf recycled here -> returned view dangles (OWN002)
        }
    }
}
