// AFTER (fixed). A `using` declaration owns the `IMemoryOwner` lifetime: the buffer is
// returned to the pool exactly once, at the end of the scope, AFTER the view has been
// read. The `owner.Memory.Span` borrow is consumed while the owner is still alive, so it
// is never read past the buffer's return. The checker is silent.
using System;
using System.Buffers;

static class MemoryPoolViewAfterDispose
{
    static void Run(int n)
    {
        using IMemoryOwner<byte> owner = MemoryPool<byte>.Shared.Rent(n);
        Consume(owner.Memory.Span);   // read while the owner is still alive
    }

    static void Consume(ReadOnlySpan<byte> data) { }
}
