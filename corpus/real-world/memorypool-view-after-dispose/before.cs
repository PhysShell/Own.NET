// BEFORE (buggy). POOL002 for MemoryPool: an `IMemoryOwner<T>` from `MemoryPool<T>`
// exposes its pooled buffer as a `Memory<T>` via `owner.Memory`. That Memory (and the
// `Span` taken from it) is a BORROW of the owner — it is only valid while the owner is
// alive. Reading the view AFTER `owner.Dispose()` (which returns the memory to the pool)
// reads memory that may already have been handed to another renter: a use-after-free.
// The fix is to read the view BEFORE disposing — or let a `using` own the lifetime
// (see after.cs). The MemoryPool twin of `arraypool-span-view-after-return`.
//
// Wrapped in a class so the extractor's per-class flow pass visits it; the helper is
// stubbed so the reduction is self-contained.
using System;
using System.Buffers;

static class MemoryPoolViewAfterDispose
{
    static void Run(int n)
    {
        IMemoryOwner<byte> owner = MemoryPool<byte>.Shared.Rent(n);
        Memory<byte> view = owner.Memory;   // a borrow of the owner's pooled buffer
        owner.Dispose();                    // returns the memory to the pool ...
        Consume(view.Span);                 // <-- BUG: ... but the view is read AFTER (use-after-free)
    }

    static void Consume(ReadOnlySpan<byte> data) { }
}
