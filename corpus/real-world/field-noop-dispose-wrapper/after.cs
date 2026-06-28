using System;
using System.IO;

// The same pass-through wrapper, but over an IN-MEMORY backing (MemoryStream).
// StreamReader's Dispose only cascades to the MemoryStream, which holds managed memory
// only, so disposing frees nothing real and leaving the field undisposed is NOT a leak.
sealed class BufferLineReader : IDisposable
{
    readonly StreamReader _reader;

    public BufferLineReader(byte[] data)
        => _reader = new StreamReader(new MemoryStream(data));

    public string? Next() => _reader.ReadLine();

    public void Dispose()
    {
        // nothing to release — _reader wraps managed memory only (no-op dispose), so the
        // extractor recognises the no-op-wrapper shape and stays silent (no OWN001).
    }
}
