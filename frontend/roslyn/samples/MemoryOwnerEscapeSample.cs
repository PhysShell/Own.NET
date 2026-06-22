using System;
using System.Buffers;

namespace Own.Samples;

// P-016 escape-via-projection (mined: ImageSharp Image.WrapMemory; CodeQL agrees — no leak).
//
// An IMemoryOwner's `.Memory` view passed as an ARGUMENT hands the OWNER off: the Memory keeps
// the owner alive (it IS the backing), so a consumer that stores it takes over the lifetime —
// the owner is not leaked at method scope. Contrast: an owner whose `.Memory` is only READ
// locally and never disposed IS a leak. Exercised with --flow-locals.

internal sealed class PixelOwner : IMemoryOwner<byte>
{
    private readonly byte[] data = new byte[16];

    public Memory<byte> Memory => this.data;

    public void Dispose() { }
}

internal static class MemoryOwnerEscape
{
    private static void Store(Memory<byte> m) { }

    // owner.Memory handed to a consumer (ambiguous transfer) -> owner escapes -> SILENT.
    public static void Transferred()
    {
        var handedOwner = new PixelOwner();
        Store(handedOwner.Memory);            // .Memory passed as an arg -> ownership handed off
    }

    // owner.Memory only READ locally (a length); owner never disposed -> real leak -> must WARN.
    public static int ReadOnlyLeak()
    {
        var leakedOwner = new PixelOwner();
        return leakedOwner.Memory.Length;     // a local read, NOT a handoff
    }
}
