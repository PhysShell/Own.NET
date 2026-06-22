using System;
using System.Buffers;
using System.IO;

namespace Own.Samples;

// Field release recognition (mined: ImageSharp). Two shapes the field detectors missed:
//   #2 null-conditional disposal `field?.Dispose()`, and
//   #3 a pooled FIELD released in a DIFFERENT member than the rent (ctor rent + Dispose
//      return), or transferred into a field-stored guard that owns/returns it.

// #2: an IDisposable field disposed via the null-conditional `?.Dispose()` -> SILENT.
public sealed class DisposesViaConditional : IDisposable
{
    private readonly MemoryStream stream = new();

    public void Dispose() => this.stream?.Dispose();   // null-conditional -> now recognized
}

// #2 control: an IDisposable field the class new's but never disposes -> must WARN.
public sealed class NeverDisposesField
{
    private readonly MemoryStream stream = new();

    public long Use() => this.stream.Length;
}

// #3: a pooled buffer FIELD rented in the ctor and Returned in Dispose (cross-member) -> SILENT.
public sealed class PoolFieldReturnedInDispose : IDisposable
{
    private readonly byte[] returnedBuf;

    public PoolFieldReturnedInDispose(int n) => this.returnedBuf = ArrayPool<byte>.Shared.Rent(n);

    public void Dispose() => ArrayPool<byte>.Shared.Return(this.returnedBuf);

    public byte First() => this.returnedBuf[0];
}

// #3 control: a pooled buffer FIELD rented but NEVER returned -> must WARN.
public sealed class PoolFieldLeaked
{
    private readonly byte[] leakedBuf;

    public PoolFieldLeaked(int n) => this.leakedBuf = ArrayPool<byte>.Shared.Rent(n);

    public byte First() => this.leakedBuf[0];
}
