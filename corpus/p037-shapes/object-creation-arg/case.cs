// A2.2 G-A: a handle flows into a CONSTRUCTOR. A2.1 walks invocation
// expressions only, so `new Wrapper(p, keep)` is a relevant call the sidecar
// never records, although the constructor has its own summary record
// (`ShapeObjCreation.Wrapper..ctor`) for the engine to apply at this site.
using System;
using System.IO;

sealed class Wrapper : IDisposable
{
    readonly Stream _s;
    readonly bool _keep;

    public Wrapper(Stream s, bool keep)
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

static class ShapeObjCreation
{
    static void Adopt(Stream p, bool keep)
    {
        using var w = new Wrapper(p, keep);
        p.Flush();
    }

    static void Reader(string path)
    {
        var s = File.OpenRead(path);
        var r = new StreamReader(s, leaveOpen: true);
        r.Dispose();
        s.Dispose();
    }
}
