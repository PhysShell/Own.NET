using System;
using System.Collections;
using System.Collections.Generic;

namespace Own.Samples;

// Issue #225 (narrowed by #238) — a user-defined `IEnumerator<T>` whose Dispose() body is provably
// EMPTY holds no resource behind the interface (IEnumerator<T> is the one interface that FORCES
// IDisposable onto a type that usually holds nothing), so a LOCAL of it never disposed cannot leak.
// Mirrors ClosedXML's Slice.Enumerator. The exemption is deliberately NOT "any type" (that was the
// #238 regression) and NOT the non-generic IEnumerator (which does not extend IDisposable). The
// negative controls below pin every edge of the narrowing. A FIELD keeps its own disposal contract
// (out of scope here), so the OwnIgnoreSample `Handle` field stand-in is unaffected.

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

// EMPTY Dispose spelled as an EXPLICIT interface implementation — the actual ClosedXML
// Slice.Enumerator form (#238 coverage): metadata name "System.IDisposable.Dispose", which a
// plain GetMembers("Dispose") lookup misses.
public sealed class ExplicitDisposeEnumerator : IEnumerator<int>
{
    private int _i;
    public int Current => _i;
    object IEnumerator.Current => Current;
    public bool MoveNext() => ++_i <= 3;
    public void Reset() => _i = 0;
    void IDisposable.Dispose() { }   // literally empty, explicit-interface spelling
}

// #238 SOUNDNESS control — the XLWorkbook shape: an empty SOURCE Dispose on a NON-enumerator
// type. An IL weaver (Janitor.Fody) can inject the real cleanup at build time, and source-level
// analysis cannot prove it doesn't — so this must STAY flagged. (`*Reader` name keeps the flat
// path exercising it too.)
public sealed class ScratchReader : IDisposable
{
    public int Read() => -1;
    public void Dispose() { }   // empty IN SOURCE only -> not provably a runtime no-op
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

// NON-empty cleanup via DisposeAsync, with the sync Dispose() an empty COMPATIBILITY no-op (a type
// implementing both IDisposable and IAsyncDisposable). The empty sync body must NOT exempt it — the
// real cleanup lives in DisposeAsync, which the flow detector treats as a release, so an undisposed
// local still leaks (Codex P2). Name ends `Reader` so both detector paths see it.
public sealed class AsyncReader : IDisposable, IAsyncDisposable
{
    private readonly System.Threading.CancellationTokenSource _cts = new();
    public int Read() => 0;
    public void Dispose() { }                                        // empty sync compat no-op
    public System.Threading.Tasks.ValueTask DisposeAsync()           // REAL cleanup
    {
        _cts.Dispose();
        return default;
    }
}

// #240 review P1 — the real async cleanup lives in a BASE class's DisposeAsync, and the base does
// NOT implement IDisposable (so the base-cascade check alone lets it through). An empty sync
// Dispose on the derived enumerator must STILL leak: an IAsyncDisposable ANYWHERE in the interface
// set (inherited included) disqualifies the exemption.
public abstract class AsyncOwnerBase : IAsyncDisposable
{
    private readonly System.Threading.CancellationTokenSource _cts = new();
    public System.Threading.Tasks.ValueTask DisposeAsync()           // REAL cleanup, on the BASE
    {
        _cts.Dispose();
        return default;
    }
}
public sealed class InheritedAsyncEnumerator : AsyncOwnerBase, IEnumerator<int>
{
    private int _i;
    public int Current => _i;
    object IEnumerator.Current => Current;
    public bool MoveNext() => ++_i <= 3;
    public void Reset() => _i = 0;
    public void Dispose() { }   // empty sync, but the base owns a real DisposeAsync
}

// #240 review round 2 P2 — the base owns a BARE DisposeAsync() and does NOT implement
// IAsyncDisposable, so neither AllInterfaces nor a current-type-only member scan catches it; only
// walking the whole base chain does. An empty sync Dispose here must STILL leak.
public abstract class BareAsyncBase
{
    private readonly System.Threading.CancellationTokenSource _cts = new();
    public System.Threading.Tasks.ValueTask DisposeAsync()           // bare, no interface, on the BASE
    {
        _cts.Dispose();
        return default;
    }
}
public sealed class BareInheritedAsyncEnumerator : BareAsyncBase, IEnumerator<int>
{
    private int _i;
    public int Current => _i;
    object IEnumerator.Current => Current;
    public bool MoveNext() => ++_i <= 3;
    public void Reset() => _i = 0;
    public void Dispose() { }   // empty sync, but the base owns a bare real DisposeAsync
}

// #240 review round 2 P2 — a NON-generic System.Collections.IEnumerator does NOT extend IDisposable,
// so pairing it with IDisposable is author-chosen, not forced: the motivating proof does not apply
// and an empty-Dispose local must STAY flagged. Pins the IEnumerator<T>-only narrowing.
public sealed class LegacyEnumerator : IEnumerator, IDisposable
{
    private int _i;
    public object Current => _i;
    public bool MoveNext() => ++_i <= 3;
    public void Reset() => _i = 0;
    public void Dispose() { }   // empty, but the type was not FORCED to implement IDisposable
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

    // SILENT: the explicit-interface empty-Dispose enumerator (#238 coverage), never disposed.
    public int CountExplicit()
    {
        var x = new ExplicitDisposeEnumerator();
        var n = 0;
        while (x.MoveNext()) n++;  // never disposed -> Dispose is empty -> SILENT
        return n;
    }

    // FLAGGED (#238 soundness control): an empty SOURCE Dispose on a NON-enumerator — a weaver
    // may add the real cleanup at build time, so the exemption must not apply -> OWN001.
    public int UseScratch()
    {
        var s = new ScratchReader();
        return s.Read();           // non-enumerator empty-in-source Dispose -> LEAK
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

    // FLAGGED (control, Codex P2): empty SYNC Dispose but a real DisposeAsync -> never disposing
    // (sync or async) leaks; the empty sync body must not exempt it.
    public int LeakAsync()
    {
        var ar = new AsyncReader();
        return ar.Read();          // never disposed (sync or async) -> LEAK
    }

    // FLAGGED (control, #240 review P1): the enumerator's own sync Dispose is empty, but its BASE
    // owns a real DisposeAsync -> an inherited IAsyncDisposable must still leak.
    public int LeakInheritedAsync()
    {
        var ia = new InheritedAsyncEnumerator();
        var n = 0;
        while (ia.MoveNext()) n++; // base DisposeAsync is real -> LEAK
        return n;
    }

    // FLAGGED (control, #240 review round 2): base owns a BARE DisposeAsync (no interface) -> the
    // base-chain scan must catch it -> LEAK.
    public int LeakBareInheritedAsync()
    {
        var ba = new BareInheritedAsyncEnumerator();
        var n = 0;
        while (ba.MoveNext()) n++; // base bare DisposeAsync is real -> LEAK
        return n;
    }

    // FLAGGED (control, #240 review round 2): non-generic IEnumerator + IDisposable is not forced ->
    // the IEnumerator<T>-only narrowing must keep it flagged -> LEAK.
    public int LeakLegacy()
    {
        var ng = new LegacyEnumerator();
        var n = 0;
        while (ng.MoveNext()) n++; // non-generic enumerator, author-coupled IDisposable -> LEAK
        return n;
    }
}
