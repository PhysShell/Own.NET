using System;
using System.Threading;

namespace Own.Samples;

// Two Npgsql re-mine precision fixes for the field-disposable (WPF003/OWN001) detector.
//
// #2  SemaphoreSlim is dispose-optional: its Dispose() only frees a LAZILY-allocated wait handle
//     (allocated solely if AvailableWaitHandle is read), so the common WaitAsync/Release usage
//     leaks nothing and an undisposed SemaphoreSlim field must be SILENT. Mined:
//     NpgsqlDataSource._setupMappingsSemaphore.
// #1  `.Close()` releases a field, exactly as it already does for LOCAL disposables (DisposesLocal
//     and the flow detector both accept Dispose/Close/DisposeAsync): a Stream / DbConnection-style
//     field cleaned up by Close() is not a leak. Mined: ReplicationConnection releases its
//     NpgsqlConnection via `await _npgsqlConnection.Close(async: true)`.

// #2: a SemaphoreSlim field new'd and never disposed -> dispose-optional -> SILENT.
public sealed class HoldsSemaphore
{
    private readonly SemaphoreSlim _gate = new SemaphoreSlim(1, 1);

    public void Use()
    {
        _gate.Wait();
        _gate.Release();
    }
}

// #2 control: the exemption is SemaphoreSlim-specific, NOT "any field" — a real owned IDisposable
// (CancellationTokenSource) new'd and never disposed must STILL warn OWN001.
public sealed class HoldsRealDisposable
{
    private readonly CancellationTokenSource _ctsControl = new CancellationTokenSource();

    public void Cancel() => _ctsControl.Cancel();
}

// #1: a field released via `.Close()` — direct and null-conditional — must be SILENT.
public sealed class ReleasesViaClose : IDisposable
{
    private readonly FakeConnection _closedConn = new FakeConnection();
    private readonly FakeConnection _closedConnQ = new FakeConnection();

    public void Dispose()
    {
        _closedConn.Close();      // Close() releases the field -> SILENT
        _closedConnQ?.Close();    // null-conditional Close() -> SILENT
    }
}

// #1 control: a field NEITHER closed NOR disposed must STILL warn OWN001.
public sealed class LeaksUnclosed : IDisposable
{
    private readonly FakeConnection _leakedConn = new FakeConnection();

    public void Dispose() { }   // never closed/disposed -> WARN
}

// A connection-like resource whose release is Close() (the DbConnection.Close() / Stream.Close() shape).
internal sealed class FakeConnection : IDisposable
{
    public void Close() { }
    public void Dispose() { }
}
