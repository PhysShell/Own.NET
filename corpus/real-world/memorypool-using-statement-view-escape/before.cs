// BEFORE (buggy). The STATEMENT form of `memorypool-using-view-escape` (POOL004). The
// MemoryPool owner is scoped by a `using (...)` STATEMENT rather than a `using`
// declaration, but the dispose semantics are identical: the owner is `Dispose()`d as the
// block exits, so `return owner.Memory` hands the caller a `Memory<T>` backed by buffer
// already returned to the pool — a dangling borrow. Both `using` syntaxes need the same
// scope-exit desugaring (CodeRabbit review on #74). The fix is to transfer ownership:
// return the `IMemoryOwner` itself (see after.cs).
//
// Wrapped in a class so the extractor's per-class flow pass visits it.
using System;
using System.Buffers;

static class MemoryPoolUsingStatementViewEscape
{
    static Memory<byte> Borrow(int n)
    {
        using (IMemoryOwner<byte> owner = MemoryPool<byte>.Shared.Rent(n))
        {
            return owner.Memory;   // <-- BUG: owner is disposed as the using block exits, so the
                                   //     caller reads a view of buffer already back in the pool
        }
    }
}
