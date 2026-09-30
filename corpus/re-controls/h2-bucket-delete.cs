// resource-effects Stage 1 hostile oracle control H2: an instance method NAMED Delete that removes an
// entry from the receiver's own collection. Truth: the bucket leaks (OWN001) and the use after Delete is
// legal. The identity answer key (CngKey.Delete only) must not fire; the M2 name-rule mutant key
// (Delete -> receiver release) MUST produce a false OWN002 and hide the real leak.
using System;
using System.Collections.Generic;

sealed class Bucket : IDisposable
{
    readonly Dictionary<string, int> _entries = new Dictionary<string, int>();

    public void Delete(string name) => _entries.Remove(name);

    public void Touch() { }

    public void Dispose() { _entries.Clear(); }
}

static class H2
{
    static void Run()
    {
        var b = new Bucket();
        b.Delete("x");
        b.Touch();
    }
}
