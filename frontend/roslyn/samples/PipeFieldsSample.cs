using System;
using System.IO.Pipelines;
using System.Threading;
using System.Threading.Tasks;

// Mined false-positive regression guard (Pipelines.Sockets.Unofficial). `System.IO.Pipelines`
// PipeReader/PipeWriter END WITH "Reader"/"Writer", so the field-disposable NAME heuristic used to
// classify them as IDisposable and flag an undisposed PipeReader/PipeWriter FIELD as a leak. But they
// are NOT IDisposable — they finish via Complete(), not Dispose(). A class that constructs such fields
// and never disposes them must produce NO finding (mirrors SocketConnection._input/_output, which the
// checker wrongly reported before IsNonDisposableReaderWriter excluded these types).
public sealed class PipeHolder
{
    private readonly PipeReader _input;
    private readonly PipeWriter _output;

    public PipeHolder()
    {
        _input = new NullReader();    // constructed (a `new`) -> a disposable-field candidate before the fix
        _output = new NullWriter();
    }

    // No Dispose: PipeReader/PipeWriter are completed by the consumer, not disposed -> not a leak.
}

// Minimal PipeReader/PipeWriter implementations so the sample is self-contained (the abstract BCL
// types resolve from the framework reference set). PipeReader/PipeWriter expose Complete(), not
// Dispose() — they are not IDisposable.
internal sealed class NullReader : PipeReader
{
    public override void AdvanceTo(SequencePosition consumed) => throw new NotImplementedException();
    public override void AdvanceTo(SequencePosition consumed, SequencePosition examined) => throw new NotImplementedException();
    public override void CancelPendingRead() => throw new NotImplementedException();
    public override void Complete(Exception exception = null) => throw new NotImplementedException();
    public override ValueTask<ReadResult> ReadAsync(CancellationToken cancellationToken = default) => throw new NotImplementedException();
    public override bool TryRead(out ReadResult result) => throw new NotImplementedException();
}

internal sealed class NullWriter : PipeWriter
{
    public override void Advance(int bytes) => throw new NotImplementedException();
    public override void CancelPendingFlush() => throw new NotImplementedException();
    public override void Complete(Exception exception = null) => throw new NotImplementedException();
    public override ValueTask<FlushResult> FlushAsync(CancellationToken cancellationToken = default) => throw new NotImplementedException();
    public override Memory<byte> GetMemory(int sizeHint = 0) => throw new NotImplementedException();
    public override Span<byte> GetSpan(int sizeHint = 0) => throw new NotImplementedException();
}
