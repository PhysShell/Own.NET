// BEFORE (buggy). POOL004 for MemoryPool, the idiomatic-`using` dangle. An
// `IMemoryOwner<T>` from `MemoryPool<T>` is held with a `using` declaration — so it is
// `Dispose()`d at scope exit — but the method RETURNS `owner.Memory`, a borrow of the
// owner's pooled buffer. The implicit dispose runs as the method returns, so the caller
// receives a `Memory<T>` backed by memory already handed back to the pool: a dangling
// borrow / use-after-free. `using owner = …; return owner.Memory;` is exactly
// `try { return owner.Memory; } finally { owner.Dispose(); }` — the MemoryPool twin of
// the ArrayPool try/finally `Memory` escape. The fix is to TRANSFER ownership: return the
// `IMemoryOwner` itself (no `using`) and let the caller own its lifetime (see after.cs).
//
// Wrapped in a class so the extractor's per-class flow pass visits it.
using System;
using System.Buffers;

static class MemoryPoolUsingViewEscape
{
    static Memory<byte> Borrow(int n)
    {
        using IMemoryOwner<byte> owner = MemoryPool<byte>.Shared.Rent(n);
        return owner.Memory;   // <-- BUG: the `using` disposes owner as we return, so the
                               //     caller gets a view of buffer already returned to the pool
    }
}
