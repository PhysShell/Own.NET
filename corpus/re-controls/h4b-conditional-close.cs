// resource-effects Stage 1 observation H4b (NOT a control that can pass or fail this track): the same
// conditional release as H4 but NAMED Close, which the PRODUCTION release name set already treats as a
// release of any tracked local. Measured under no key only, to record the pre-existing behaviour of
// the name set; never repaired here.
using System;

sealed class Handle : IDisposable
{
    bool _open = true;

    public void Close(bool really)
    {
        if (really)
        {
            Dispose();
        }
    }

    public void Touch() { }

    public void Dispose() { _open = false; }
}

static class H4B
{
    static void Run()
    {
        var h = new Handle();
        h.Close(false);
        h.Touch();
        h.Dispose();
    }
}
