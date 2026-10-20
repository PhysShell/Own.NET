// N1-F0 oracle controls (00-preregistration.md, F0-B). Written before the first run.
// Methods N<n>_* must be SILENT; methods P_* must be REPORTED.
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Threading.Tasks;
using Microsoft.Extensions.DependencyInjection;

namespace OwnershipControls;

public interface IFoo : IAsyncDisposable { Task PingAsync(); }
public interface IConn : IAsyncDisposable { Task<IFoo> OpenAsync(); }

public static class Cache
{
    public static IFoo Get(string key) => throw new NotSupportedException();
}

public static class Remote
{
    public static Task<IFoo> CreateAsync(string url) => throw new NotSupportedException();
}

public sealed class Wrap : IAsyncDisposable
{
    private readonly IFoo _inner;
    public Wrap(IFoo inner) { _inner = inner; }
    public ValueTask DisposeAsync() => _inner.DisposeAsync();
}

public sealed class Holder : IAsyncDisposable
{
    private readonly IServiceProvider _sp;
    private readonly IConn _conn;
    private IFoo? _foo;
    private IFoo? _shared;
    private readonly ConcurrentDictionary<string, IFoo> _owned = new();
    private readonly Dictionary<string, IFoo> _cache = new();

    public Holder(IServiceProvider sp, IConn conn) { _sp = sp; _conn = conn; }

    private static Task StepAsync() => Task.Delay(1);

    // ---- negative controls: must be silent ----

    public async Task N1_DiResolved()
    {
        var s = _sp.GetRequiredService<IFoo>();
        await StepAsync();
        _foo = s;
    }

    public async Task N2_Borrowed(IFoo given)
    {
        await StepAsync();
        _foo = given;
    }

    public async Task N3_SharedNeverDisposed(string k)
    {
        var c = Cache.Get(k);
        await StepAsync();
        _shared = c;
    }

    public async Task N4_CachingFactoryNeverDisposed(string k)
    {
        var c = await Remote.CreateAsync(k);
        await c.PingAsync();
        _cache[k] = c;
    }

    public async Task N5_HandOverFirst(string k)
    {
        var c = await Remote.CreateAsync(k);
        _owned[k] = c;
        await c.PingAsync();
    }

    public async Task N6_TryCatchDispose(string k)
    {
        var c = await Remote.CreateAsync(k);
        try
        {
            await c.PingAsync();
        }
        catch
        {
            await c.DisposeAsync();
            throw;
        }
        _owned[k] = c;
    }

    public async Task N7_PublishedFlag(string k)
    {
        IFoo? c = null;
        var published = false;
        try
        {
            c = await Remote.CreateAsync(k);
            await c.PingAsync();
            _owned[k] = c;
            published = true;
        }
        finally
        {
            if (!published && c is not null) await c.DisposeAsync();
        }
    }

    public async Task N8_LocalUsing(string k)
    {
        await using var c = await Remote.CreateAsync(k);
        await c.PingAsync();
    }

    public async Task<IFoo> N9_Returned(string k)
    {
        var c = await Remote.CreateAsync(k);
        await c.PingAsync();
        return c;
    }

    // ---- positive samples: must be reported ----

    // P-R: awaited factory, throwing call on the result, then stored into a dictionary T disposes from
    public async Task P_R(string k)
    {
        var c = await Remote.CreateAsync(k);
        await c.PingAsync();
        _owned[k] = c;
    }

    // P-B: awaited interface factory, throwing call, then dictionary store
    public async Task P_B(string k)
    {
        IFoo ch = await _conn.OpenAsync();
        await ch.PingAsync();
        _owned[k] = ch;
    }

    // P-X: factory result wrapped in an in-source type that disposes it, after a throwing call
    public async Task<Wrap> P_X()
    {
        var c = await Remote.CreateAsync("x");
        await StepAsync();
        return new Wrap(c);
    }

    public async ValueTask DisposeAsync()
    {
        if (_foo is not null) await _foo.DisposeAsync();
        foreach (var v in _owned.Values) await v.DisposeAsync();
        if (_owned.TryRemove("k", out var one)) await one.DisposeAsync();
    }
}
