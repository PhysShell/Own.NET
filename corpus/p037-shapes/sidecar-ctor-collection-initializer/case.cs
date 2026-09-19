using System;
using System.IO;
using System.Collections.Generic;

// A2.2-2 NEGATIVE: a collection initializer element is container_construction, not a
// constructor argument; the parameterless `new List<Stream>()` binds nothing.
static class ShapeCtorCollectionInitializer
{
    static void Caller(string path)
    {
        var keep = File.OpenRead(path);
        var s = File.OpenRead(path);
        var l = new List<Stream> { s };
        keep.Dispose();
    }
}
