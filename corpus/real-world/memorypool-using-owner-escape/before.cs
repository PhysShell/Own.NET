// BEFORE (buggy). The bare-owner `using` dangle — the twin of `memorypool-using-view-escape`. An
// `IMemoryOwner<T>` from `MemoryPool<T>` is held with a `using` declaration — so it is `Dispose()`d
// at scope exit — but the method RETURNS THE OWNER ITSELF. The implicit dispose runs as the method
// returns, so the caller receives an `IMemoryOwner<T>` already disposed (its pooled buffer handed
// back to the pool): a dangling owner / use-after-free. `using owner = …; return owner;` is exactly
// `try { return owner; } finally { owner.Dispose(); }`. The fix TRANSFERS ownership: drop the
// `using` and let the caller own and dispose it (see after.cs).
//
// Wrapped in a class so the extractor's per-class flow pass visits it.
using System;
using System.Buffers;

static class MemoryPoolUsingOwnerEscape
{
    static IMemoryOwner<byte> Borrow(int n)
    {
        using IMemoryOwner<byte> owner = MemoryPool<byte>.Shared.Rent(n);
        return owner;   // <-- BUG: the `using` disposes owner as we return, so the caller gets an
                        //     IMemoryOwner already returned to the pool
    }
}
