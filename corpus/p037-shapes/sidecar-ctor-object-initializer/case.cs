using System;
using System.IO;

// A2.2-2 NEGATIVE: an object initializer is storage (a named exclusion), not a constructor
// argument. `new Holder { Inner = s }` binds nothing and gets no call fact.
static class ShapeCtorObjectInitializer
{
    sealed class Holder { public Stream? Inner { get; set; } }
    static void Caller(string path)
    {
        var keep = File.OpenRead(path);
        var s = File.OpenRead(path);
        var h = new Holder { Inner = s };
        keep.Dispose();
    }
}
