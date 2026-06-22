// AFTER (fixed). Ownership is TRANSFERRED to the caller: the method returns the
// `IMemoryOwner<T>` directly (no `using` scope), so nothing is disposed here and the pooled
// buffer stays alive for as long as the caller keeps the owner. No dangling borrow, so the
// checker is silent.
using System;
using System.Buffers;

static class MemoryPoolUsingStatementViewEscape
{
    static IMemoryOwner<byte> Borrow(int n)
    {
        return MemoryPool<byte>.Shared.Rent(n);   // transfer ownership — the caller disposes it
    }
}
