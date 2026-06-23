using System;

namespace Own.Samples;

// `.Close()` releases a field, exactly as it already does for LOCAL disposables (DisposesLocal and the
// flow detector both accept Dispose/Close/DisposeAsync): a Stream / DbConnection-style field cleaned up
// by Close() is not a leak. Mined: Npgsql's ReplicationConnection releases its NpgsqlConnection field
// via `await _npgsqlConnection.Close(async: true)`.

// a field released via `.Close()` — direct and null-conditional — must be SILENT.
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

// control: a field NEITHER closed NOR disposed must STILL warn OWN001.
public sealed class LeaksUnclosed : IDisposable
{
    private readonly FakeConnection _leakedConn = new FakeConnection();

    public void Dispose() { }   // never closed/disposed -> WARN
}

// Codex/CodeRabbit control: Close() must target THIS instance's field. Closing ANOTHER instance of the
// SAME class's same-named private field must NOT credit this object — and note a field-symbol
// ContainingType check could not tell them apart (same class), so this leans on the `this`/bare receiver.
// This object's own _xconn is never closed, so it STILL leaks.
public sealed class ClosesOtherInstanceField : IDisposable
{
    private readonly FakeConnection _xconn = new FakeConnection();

    public void CloseOther(ClosesOtherInstanceField other)
    {
        other._xconn.Close();    // closes ANOTHER instance's field -> must NOT credit this._xconn
    }

    public void Dispose() { }    // this._xconn is never closed -> WARN OWN001
}

// A connection-like resource whose release is Close() (the DbConnection.Close() / Stream.Close() shape).
internal sealed class FakeConnection : IDisposable
{
    public void Close() { }
    public void Dispose() { }
}
