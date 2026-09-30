// resource-effects Stage 1 hostile oracle control H4: an instance method NAMED Release whose release is
// CONDITIONAL on its argument. Truth: no finding (the use after Release(false) is legal, the final
// Dispose is the one release). The identity answer key must not fire; the M2 name-rule mutant key
// (Release -> receiver release) MUST produce a false OWN002 (and possibly OWN003).
using System;

sealed class Handle : IDisposable
{
    bool _open = true;

    public void Release(bool really)
    {
        if (really)
        {
            Dispose();
        }
    }

    public void Touch() { }

    public void Dispose() { _open = false; }
}

static class H4
{
    static void Run()
    {
        var h = new Handle();
        h.Release(false);
        h.Touch();
        h.Dispose();
    }
}
