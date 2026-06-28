using System;
using System.IO;

// A BCL pass-through wrapper (StreamReader) held as an owned field and never disposed.
// Whether this is a leak depends ENTIRELY on the backing it wraps: here it wraps a real
// file handle, so Dispose() would release an OS resource and skipping it leaks.
sealed class FileLineReader : IDisposable
{
    readonly StreamReader _reader;

    public FileLineReader(string path)
        => _reader = new StreamReader(new FileStream(path, FileMode.Open));

    public string? Next() => _reader.ReadLine();

    public void Dispose()
    {
        // BUG: _reader (and the FileStream it owns) is never disposed — a real OS handle
        // leaks → OWN001. The backing is NOT in-memory, so the no-op exemption must NOT
        // apply here.
    }
}
