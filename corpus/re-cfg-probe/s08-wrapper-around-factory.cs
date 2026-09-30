// Stage 2A shape s08: a factory and a wrapper around it; also a direct `return new`. Truth: Make, Make2 and Make3 return fresh.
using System;
sealed class R : IDisposable { public bool IsOpen => true; public void Touch() { } public void Dispose() { } }
static class S08
{
    static R Make()
    {
        var r = new R();
        return r;
    }

    static R Make2()
    {
        return Make();
    }

    static R Make3()
    {
        return new R();
    }
}
