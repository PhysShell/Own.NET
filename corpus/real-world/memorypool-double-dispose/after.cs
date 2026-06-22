// AFTER (fixed). A `using` declaration disposes the owner exactly once, at the end
// of the scope, on every path — no second Dispose. The pooled memory is released
// once and returned to the pool cleanly, so the checker is silent.
using System;
using System.Buffers;

static class MemoryPoolDoubleDispose
{
    static void Run(int n)
    {
        using IMemoryOwner<byte> owner = MemoryPool<byte>.Shared.Rent(n);
        Work(owner.Memory);
    }

    static void Work(Memory<byte> data) { }
}
