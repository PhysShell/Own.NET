using System;
using System.IO;

// A2.2-2: a handle bound to a constructor's `params` slot is opaque AND keeps the call relevant,
// the same relevance/representability separation the A' invocation witnesses pin.
static class ShapeCtorParamsHandle
{
    sealed class Sink : IDisposable { public Sink(params Stream[] xs) { } public void Dispose() { } }
    static void Caller(string path) { var s = File.OpenRead(path); var w = new Sink(s); }
}
