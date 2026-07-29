using System;

namespace Own.Corpus.Mini;

// An IDisposable field the class constructs and never disposes: OWN001
// [resource: disposable field], anchored at the field declaration.
public sealed class FieldLeak
{
    private readonly Handle _handle = new Handle();

    public bool Open => _handle.IsOpen;
}

// The same field, disposed on teardown -> silent.
public sealed class FieldDisposed : IDisposable
{
    private readonly Handle _handle = new Handle();

    public bool Open => _handle.IsOpen;

    public void Dispose()
    {
        _handle.Dispose();
    }
}
