// A Memory<T> VIEW of a pooled buffer ESCAPES the method (returned to the caller) AFTER the buffer
// was returned to the pool. Unlike a `Span` (a ref struct the compiler keeps inside the method), a
// `Memory<T>` CAN leave the method — so this dangling view reaches the caller, who then reads/writes
// memory the pool has already recycled to someone else (a silent cross-tenant corruption). The
// borrow outlives its owner: a use-after-return surfaced at the ESCAPE (return) site.
//
// Wrapped in a class so the extractor's per-class flow pass visits it.
using System;
using System.Buffers;

static class PoolMemoryViewEscape
{
    static Memory<byte> Render(int n)
    {
        byte[] buf = ArrayPool<byte>.Shared.Rent(n);
        Memory<byte> view = buf.AsMemory(0, n);      // view BORROWS buf
        ArrayPool<byte>.Shared.Return(buf);          // buf goes back to the pool (recycled) ...
        return view;                                 // ... but a view of it ESCAPES -> dangling (OWN002)
    }
}
