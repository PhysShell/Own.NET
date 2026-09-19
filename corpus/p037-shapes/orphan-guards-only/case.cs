using System;
using System.IO;

// A2.2-3P: no handle at all — a field disposed under a `disposing` guard — so the legacy pass
// never looks at the method; the orphan carries the eligible guard and no call.
static class ShapeOrphanGuardsOnly
{
    sealed class Holder : IDisposable
    {
        readonly FileStream _f = File.OpenRead("x");
        bool _done;
        public void Dispose() { Dispose(true); }
        void Dispose(bool disposing) { if (disposing) { _f.Dispose(); _done = true; } }
    }
}
