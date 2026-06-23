using System;
using System.Threading;

namespace Own.Samples;

// WPF003/OWN001 field disposed through a local ALIAS (mined: Npgsql NpgsqlDataSource). A field copied to a
// local (`var cts = _cts;`) and disposed through that alias (`cts.Dispose();`) IS released: the
// alias and the field reference the same object. The field-disposable detector must credit the
// FIELD so it is not reported as an undisposed leak. Contrast the controls below.
public sealed class AliasDisposes : IDisposable
{
    private readonly CancellationTokenSource _aliased = new CancellationTokenSource();
    private readonly CancellationTokenSource _aliasedQ = new CancellationTokenSource();

    public void Dispose()
    {
        var a = _aliased;        // bare-field alias
        a.Dispose();             // disposed through the alias -> _aliased released -> SILENT

        var q = this._aliasedQ;  // this-qualified alias
        q?.Dispose();            // null-conditional dispose through the alias -> _aliasedQ released -> SILENT
    }
}

// Control: a field aliased to a local that is NEVER disposed must STILL leak — the alias
// recognition requires an actual `.Dispose()` on the alias, not merely a copy.
public sealed class AliasNeverDisposes : IDisposable
{
    private readonly CancellationTokenSource _neverDisposed = new CancellationTokenSource();

    public void Dispose()
    {
        var a = _neverDisposed;  // aliased but never disposed -> _neverDisposed leaks -> WARN OWN001
        _ = a.Token;
    }
}

// Control: a REASSIGNED alias no longer tracks the field — disposing it releases the NEW object,
// not the field, so the field must STILL leak (the reassignment gate declines to credit it).
public sealed class ReboundAliasLeaks : IDisposable
{
    private readonly CancellationTokenSource _rebound = new CancellationTokenSource();

    public void Dispose()
    {
        var a = _rebound;                     // starts as the field...
        a = new CancellationTokenSource();    // ...but is rebound to a NEW source
        a.Dispose();                          // disposes the new one, not _rebound -> WARN OWN001
    }
}
