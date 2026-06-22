// FIXED. The callback guards on the disposed flag before it touches the view, so a late, already-
// dispatched callback bails before reading a buffer that has been returned to the pool. (Equivalently,
// drain the dispatcher queue before disposing.) The extractor sees the opening `if (_disposed) return;`
// guard precede the view read and stays silent.
using System;
using System.Buffers;

public sealed class FrameDecoder : IDisposable
{
    private readonly IMemoryOwner<byte> _owner;
    private readonly Memory<byte> _view;
    private readonly IDisposable _sub;
    private bool _disposed;

    public FrameDecoder(int n, IEventBus bus)
    {
        _owner = MemoryPool<byte>.Shared.Rent(n);
        _view = _owner.Memory;
        _sub = bus.Subscribe<FrameReady>(OnFrameReady);
    }

    private void OnFrameReady(FrameReady e)
    {
        if (_disposed) return;   // do not touch the pooled buffer after it is returned
        Sink.Write(_view.Span);
    }

    public void Dispose()
    {
        _disposed = true;
        _sub.Dispose();
        _owner.Dispose();
    }
}

// Minimal in-file stand-ins so the reduction is self-contained.
public interface IEventBus
{
    IDisposable Subscribe<T>(Action<T> handler);
}

public sealed class FrameReady { }

internal static class Sink
{
    public static void Write(ReadOnlySpan<byte> data) { }
}
