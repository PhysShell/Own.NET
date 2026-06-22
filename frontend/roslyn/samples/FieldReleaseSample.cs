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

// #3: a pooled buffer FIELD transferred into a field-stored guard (#80 transfer at field
// level) — the guard owns and returns it -> SILENT.
public sealed class PoolFieldTransferredToGuard
{
    private readonly byte[] guardedBuf;
    private readonly BufferGuard guard;

    public PoolFieldTransferredToGuard(int n)
    {
        this.guardedBuf = ArrayPool<byte>.Shared.Rent(n);
        this.guard = new BufferGuard(this.guardedBuf);   // ownership handed to the guard
    }
}

public sealed class BufferGuard
{
    private byte[]? held;

    public BufferGuard(byte[] b) => this.held = b;

    public void Release()
    {
        ArrayPool<byte>.Shared.Return(this.held!);
        this.held = null;
    }
}

// #3 control: a pooled buffer FIELD rented but NEVER returned/transferred -> must WARN.
public sealed class PoolFieldLeaked
{
    private readonly byte[] leakedBuf;

    public PoolFieldLeaked(int n) => this.leakedBuf = ArrayPool<byte>.Shared.Rent(n);

    public byte First() => this.leakedBuf[0];
}
