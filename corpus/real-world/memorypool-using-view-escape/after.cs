// AFTER (fixed). Ownership is TRANSFERRED to the caller: the method returns the
// `IMemoryOwner<T>` itself (no `using`), so nothing is disposed here. The caller owns the
// owner's lifetime (`using var owner = Borrow(n); … owner.Memory …`) and the pooled buffer
// stays alive as long as the returned view is used. No dangling borrow, so the extractor
// untracks the escaped owner and the checker is silent.
using System;
using System.Buffers;

static class MemoryPoolUsingViewEscape
{
    static IMemoryOwner<byte> Borrow(int n)
    {
        IMemoryOwner<byte> owner = MemoryPool<byte>.Shared.Rent(n);
        return owner;   // transfer ownership to the caller — the caller disposes it
    }
}
