// BEFORE (buggy). POOL003 for the OTHER pool: a `MemoryPool<T>` hands back an
// `IMemoryOwner<T>` released by `Dispose()` (there is no `Return`). Disposing the
// same owner twice — here on the success path AND again in `finally` — is a double
// release: the same memory can later be handed to two renters at once, exactly the
// corruption dotnet/runtime#33767 describes for ArrayPool double-return. The fix is
// to dispose exactly once (a `using` owner, see after.cs).
//
// Wrapped in a class so the extractor's per-class flow pass visits it; the helper
// is stubbed so the reduction is self-contained.
using System;
using System.Buffers;

static class MemoryPoolDoubleDispose
{
    static void Run(int n)
    {
        IMemoryOwner<byte> owner = MemoryPool<byte>.Shared.Rent(n);
        try
        {
            Work(owner.Memory);
            owner.Dispose();     // disposed here ...
        }
        finally
        {
            owner.Dispose();     // <-- ... and again here (double release)
        }
    }

    static void Work(Memory<byte> data) { }
}
