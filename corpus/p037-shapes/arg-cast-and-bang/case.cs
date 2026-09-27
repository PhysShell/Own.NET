// A2.2 G-C: a handle behind a VALUE-PRESERVING wrapper is still the handle.
// `(Stream)p` (reference conversion) and `p!` (no runtime effect) are the same
// object as `p`, so the slot is `param`; A2.1 loses the whole call record
// because the argument is not a bare identifier. A boxing cast is NOT value-
// preserving: its slot stays opaque, but the call is still relevant.
using System;
using System.IO;

struct Handle : IDisposable
{
    public void Dispose() { }
}

static class ShapeCastBang
{
    static void Keep(Stream s, bool keep)
    {
        if (!keep)
        {
            s.Dispose();
        }
    }

    static void Sink(object o) { }

    static void Cast(Stream p, bool keep)
    {
        Keep((Stream)p, keep);
    }

    static void Bang(Stream? p, bool keep)
    {
        Keep(p!, keep);
    }

    static void Boxed(Handle h)
    {
        Sink((object)h);
    }
}
