// AFTER (fixed). Ownership is TRANSFERRED to the caller: no `using`, so the owner is NOT disposed at
// scope exit — the method hands back a live `IMemoryOwner<T>` and the caller owns its lifetime
// (disposes it when done). A bare owner returned WITHOUT `using` is a genuine ownership transfer, so
// the flow pass does not track it and the checker stays silent.
using System;
using System.Buffers;

static class MemoryPoolUsingOwnerEscape
{
    static IMemoryOwner<byte> Borrow(int n)
    {
        IMemoryOwner<byte> owner = MemoryPool<byte>.Shared.Rent(n);   // no `using` -> transfer
        return owner;   // caller owns and disposes it
    }
}
