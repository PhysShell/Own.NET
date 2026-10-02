// A2.2 G-A with NAMED arguments in reversed source order: the constructor's
// slots must bind by declared ordinal (0 = s, 1 = keep), exactly as named
// arguments to a method already do.
using System;
using System.IO;

sealed class NamedWrapper : IDisposable
{
    readonly Stream _s;
    readonly bool _keep;

    public NamedWrapper(Stream s, bool keep)
    {
        _s = s;
        _keep = keep;
    }

    public void Dispose()
    {
        if (!_keep)
        {
            _s.Dispose();
        }
    }
}

static class ShapeObjCreationNamed
{
    static void Adopt(Stream p)
    {
        var w = new NamedWrapper(keep: true, s: p);
        w.Dispose();
    }
}
