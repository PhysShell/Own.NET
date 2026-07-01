using System;
using System.Buffers;

sealed class Holder : IDisposable
{
    readonly int[] _buf;
    public Holder(int[] buf) => _buf = buf;
    public void Dispose() => ArrayPool<int>.Shared.Return(_buf);
}

static class Demo
{
    // FIX: the rented buffer is wrapped into a local Holder that is RETURNED — ownership transfers to
    // the Holder (which Returns the buffer on Dispose), so the buffer does not leak here. The extractor
    // follows the buffer through the wrapper local because that local provably leaves the method
    // (`return holder`), so it stays silent. Mirrors StackExchange.Redis Lease<T>.Create.
    public static Holder Run(int n)
    {
        var buf = ArrayPool<int>.Shared.Rent(n);
        var holder = new Holder(buf);
        return holder;
    }
}
