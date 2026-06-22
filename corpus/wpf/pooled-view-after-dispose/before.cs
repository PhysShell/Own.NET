// BUGGY (representative pooled-buffer pattern; the C# extractor catches this end-to-end via its
// field-mediated use-after-dispose pass extended to pooled owners and their Memory views).
//
// A type rents a pooled buffer (`IMemoryOwner<byte>` from `MemoryPool<byte>`), keeps a `Memory<byte>`
// VIEW of it IN A FIELD, and subscribes a handler to an event source. On teardown Dispose() returns
// the buffer to the pool (disposing the owner), but a callback already queued on the dispatcher still
// runs after Dispose() and reads the field-held view — a `Memory` backed by a buffer already handed
// back to the pool: a dangling borrow / use-after-free (an `ObjectDisposedException` or stale/torn
// bytes from the next renter). The view field aliases the owner, so reading it after the owner's
// Dispose is a use of the owner after release. The fix (after.cs) guards the handler on a disposed
// flag before it touches the view.
using System;
using System.Buffers;

public sealed class FrameDecoder : IDisposable
{
    private readonly IMemoryOwner<byte> _owner;
    private readonly Memory<byte> _view;
    private readonly IDisposable _sub;

    public FrameDecoder(int n, IEventBus bus)
    {
        _owner = MemoryPool<byte>.Shared.Rent(n);
        _view = _owner.Memory;                       // a view of the pooled buffer, kept in a field
        _sub = bus.Subscribe<FrameReady>(OnFrameReady);
    }

    private void OnFrameReady(FrameReady e)
    {
        // a late, already-dispatched callback: runs after Dispose()
        Sink.Write(_view.Span);   // <-- reads a view of a buffer already returned to the pool
    }

    public void Dispose()
    {
        _sub.Dispose();
        _owner.Dispose();   // pooled buffer returned; _view now dangles
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
