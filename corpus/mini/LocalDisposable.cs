using System;

namespace Own.Corpus.Mini;

// A local IDisposable the method constructs and never disposes, not `using`-guarded
// and not handed out: OWN001 [resource: disposable].
public sealed class LocalDisposableLeak
{
    public bool Leaks()
    {
        var handle = new Handle();
        return handle.IsOpen;
    }

    // `using` releases on every path -> silent.
    public bool Guarded()
    {
        using var handle = new Handle();
        return handle.IsOpen;
    }

    // Returned = ownership transferred out -> silent (the caller owns it now).
    public Handle Transferred()
    {
        var handle = new Handle();
        return handle;
    }
}
