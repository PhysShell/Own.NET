using System;
using System.Buffers;

// A wrapper that takes ownership of a rented buffer and returns it to the pool on Dispose.
sealed class Holder : IDisposable
{
    readonly int[] _buf;
    public Holder(int[] buf) => _buf = buf;
    public void Dispose() => ArrayPool<int>.Shared.Return(_buf);
}

static class Demo
{
    // BUG: the rented buffer is wrapped into a LOCAL Holder that never leaves the method — it is
    // dropped (never disposed, never returned, never handed out) — so the buffer is genuinely never
    // returned to the pool. A real pooled-buffer leak (OWN001). The wrapper being method-scoped is
    // exactly the case the transfer exemption must NOT cover.
    public static void Run(int n)
    {
        var buf = ArrayPool<int>.Shared.Rent(n);
        var holder = new Holder(buf);   // method-scoped; dropped -> buffer leaks
        _ = holder.GetHashCode();
    }
}
