// Ablation of the three MISSED reproductions (not scored): each variant removes one feature of
// the buggy reproduction, to see which feature silences CA2000 (AllPaths).
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Runtime.CompilerServices;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.DependencyInjection;
using Repro;
using Stubs;

namespace Ablation;

// ---- X: ServiceProvider from BuildServiceProvider, passed to GetService/GetServices before the throw ----
public sealed class XNoResolve
{
    private readonly IDbInitializer _db;
    public XNoResolve(IDbInitializer db) { _db = db; }

    // X minus the GetService/GetServices calls on the provider
    public async Task<PluginHost> BuildAsync(CancellationToken ct = default)
    {
        var services = new ServiceCollection();
        var provider = services.BuildServiceProvider(validateScopes: false); // ACQ:X-noresolve
        await _db.InitializeAsync(ct).ConfigureAwait(false);
        return new PluginHost(provider);
    }
}

public sealed class XOnlyResolve
{
    // X with the GetService call kept and the await removed (the resolve is the only step before hand-over)
    public static PluginHost Build()
    {
        var services = new ServiceCollection();
        var provider = services.BuildServiceProvider(validateScopes: false); // ACQ:X-onlyresolve
        provider.GetRequiredService<IDbInitializer>();
        return new PluginHost(provider);
    }
}

// ---- B: IChannel is an interface obtained from an interface method ----
public sealed class ChannelClass : IAsyncDisposable, IDisposable
{
    public Task BasicQosAsync(uint size, ushort count, bool global, CancellationToken ct = default) => Task.CompletedTask;
    public ValueTask DisposeAsync() => default;
    public void Dispose() { }
}

public interface IConnectionOfClass { Task<ChannelClass> CreateChannelAsync(CancellationToken ct = default); }

public sealed class BClassChannel
{
    private IConnectionOfClass? _connection;
    private readonly IStep2 _step;
    private readonly ConcurrentDictionary<string, ChannelClass> _channels = new();
    public BClassChannel(IStep2 step, IConnectionOfClass c) { _step = step; _connection = c; }

    // B with a sealed class instead of the IChannel interface; throwing step kept opaque
    public async IAsyncEnumerable<string> ConsumeAsync([EnumeratorCancellation] CancellationToken ct = default)
    {
        ChannelClass ch = await _connection!.CreateChannelAsync(ct).ConfigureAwait(false); // ACQ:B-class
        await _step.RunAsync().ConfigureAwait(false);
        _channels["id"] = ch;
        yield return "tag";
    }
}

public sealed class BNoIterator
{
    private IConnection? _connection;
    private readonly ConcurrentDictionary<string, IChannel> _channels = new();
    public BNoIterator(IConnection c) { _connection = c; }

    // B as a plain async method instead of an async iterator
    public async Task<string> ConsumeAsync(ushort prefetch, CancellationToken ct = default)
    {
        IChannel ch = await _connection!.CreateChannelAsync(ct).ConfigureAwait(false); // ACQ:B-noiter
        await ch.BasicQosAsync(0, prefetch, false, ct).ConfigureAwait(false);
        _channels["id"] = ch;
        return "tag";
    }
}

public sealed class BOpaqueStep
{
    private IConnection? _connection;
    private readonly IStep2 _step;
    private readonly ConcurrentDictionary<string, IChannel> _channels = new();
    public BOpaqueStep(IStep2 step, IConnection c) { _step = step; _connection = c; }

    // B with the throwing step moved off the channel (the channel is not the receiver of the throwing call)
    public async Task<string> ConsumeAsync(CancellationToken ct = default)
    {
        IChannel ch = await _connection!.CreateChannelAsync(ct).ConfigureAwait(false); // ACQ:B-opaque
        await _step.RunAsync().ConfigureAwait(false);
        _channels["id"] = ch;
        return "tag";
    }
}

// ---- R: the leaked client is the receiver of the throwing call, inside a catch-all retry loop ----
public sealed class RNoCatchAll
{
    private readonly ConcurrentDictionary<string, McpClient> _clients = new();

    // R without the swallowing catch(Exception) / retry loop
    public async Task ConnectServerAsync(string name, Uri url, CancellationToken ct)
    {
        var transport = new HttpClientTransport(url);
        var newClient = await McpClient.CreateAsync(transport, null, cancellationToken: ct); // ACQ:R-nocatch
        var tools = await newClient.ListToolsAsync(cancellationToken: ct);
        _clients[name] = newClient;
        GC.KeepAlive(tools);
    }
}

public sealed class ROpaqueStep
{
    private readonly IStep2 _step;
    private readonly ConcurrentDictionary<string, McpClient> _clients = new();
    public ROpaqueStep(IStep2 step) { _step = step; }

    // R without the catch-all and with the throwing step moved off the client
    public async Task ConnectServerAsync(string name, Uri url, CancellationToken ct)
    {
        var transport = new HttpClientTransport(url);
        var newClient = await McpClient.CreateAsync(transport, null, cancellationToken: ct); // ACQ:R-opaque
        await _step.RunAsync();
        _clients[name] = newClient;
    }
}

public interface IStep2 { Task RunAsync(); }

// ---- P9: is BuildServiceProvider's result tracked at all? (dispose after an opaque await) ----
public sealed class P9Provider
{
    private readonly IStep2 _step;
    public P9Provider(IStep2 step) { _step = step; }

    public async Task Run()
    {
        var provider = new ServiceCollection().BuildServiceProvider(); // ACQ:P9
        await _step.RunAsync();
        provider.Dispose();
    }
}
