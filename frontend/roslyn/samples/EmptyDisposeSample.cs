using System;
using System.Collections;
using System.Collections.Generic;

namespace Own.Samples;

// Issue #225 — a user-defined type whose Dispose() body is provably EMPTY holds no resource behind
// the interface (it implements IDisposable only to satisfy a contract, e.g. IEnumerator<T>), so a
// LOCAL of it that is never disposed cannot leak. Generalises the named-BCL no-op exemption
// (field-notes entry 9 / IsNoOpDisposeWrapper) to any type. Mirrors ClosedXML's Slice.Enumerator.
// Negative controls prove it does not over-widen. A FIELD keeps its own disposal contract (out of
// scope here), so the OwnIgnoreSample `Handle` field stand-in is unaffected.

// EMPTY Dispose — implements IDisposable only because IEnumerator<T> requires it (the ClosedXML
// shape). Its Dispose does literally nothing.
public sealed class EmptyDisposeEnumerator : IEnumerator<int>
{
    private int _i;
    public int Current => _i;
    object IEnumerator.Current => Current;
    public bool MoveNext() => ++_i <= 3;
    public void Reset() => _i = 0;
    public void Dispose() { }   // literally empty -> no resource
}

// EMPTY Dispose on a name that ALSO matches the flat (non-flow) name heuristic (`*Reader`), so the
// non-flow local-disposable path exercises the same exemption.
public sealed class ScratchReader : IDisposable
{
    public int Read() => -1;
    public void Dispose() { }   // empty -> no resource
}

// NON-empty Dispose — a real owned resource released in Dispose. A local never disposed LEAKS.
public sealed class RealResource : IDisposable
{
    private bool _closed;
    public void Touch() { }
    public void Dispose() { _closed = true; }   // has a statement -> not provably empty
}

// NON-empty Dispose, name matches the flat heuristic — the flat-path control.
public sealed class LeakyReader : IDisposable
{
    public int Read() => 0;
    public void Dispose() { GC.SuppressFinalize(this); }   // real work -> stays flagged
}

// Empty-bodied OVERRIDE, but the BASE owns a real Dispose — skipping this type's empty Dispose would
// skip the base's cascade, so a local of it must STAY flagged.
public class BaseWithRealDispose : IDisposable
{
    public void Ping() { }
    public virtual void Dispose() { GC.SuppressFinalize(this); }
}
public sealed class EmptyOverrideOverRealBase : BaseWithRealDispose
{
    public override void Dispose() { }   // empty, but base.Dispose does real work
}

public sealed class EmptyDisposeConsumers
{
    // SILENT: an empty-Dispose enumerator local, iterated and never disposed (the ClosedXML shape).
    public int CountEmpty()
    {
        var e = new EmptyDisposeEnumerator();
        var n = 0;
        while (e.MoveNext()) n++;   // never disposed -> Dispose is empty -> SILENT
        return n;
    }

    // SILENT: an empty-Dispose `*Reader` local (flat-path name match) never disposed.
    public int UseScratch()
    {
        var s = new ScratchReader();
        return s.Read();           // never disposed -> Dispose is empty -> SILENT
    }

    // FLAGGED (control): a real IDisposable local never disposed -> OWN001.
    public void LeakReal()
    {
        var r = new RealResource();
        r.Touch();                 // used, never disposed -> LEAK
    }

    // FLAGGED (control): a non-empty `*Reader` local never disposed -> OWN001 (flat path).
    public int LeakReader()
    {
        var lr = new LeakyReader();
        return lr.Read();          // never disposed -> LEAK
    }

    // FLAGGED (control): empty override, but the base Dispose does real work -> OWN001.
    public void LeakDerived()
    {
        var d = new EmptyOverrideOverRealBase();
        d.Ping();                  // base.Dispose() is real -> LEAK
    }
}
