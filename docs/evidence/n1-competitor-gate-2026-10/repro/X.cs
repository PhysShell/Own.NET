// X: NexusFFXIV/NexusKit#34, PluginHostBuilder.BuildAsync. ServiceCollection/ServiceProvider are real.
using System;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.DependencyInjection;

namespace Repro;

public interface IDbInitializer { Task InitializeAsync(CancellationToken ct); }
public interface IBackgroundService { }

public sealed class PluginHost : IAsyncDisposable
{
    private readonly ServiceProvider _provider;
    public PluginHost(ServiceProvider provider) { _provider = provider; }
    public ValueTask DisposeAsync() => _provider.DisposeAsync();
}

public sealed class XBuggy
{
    private readonly Action<IServiceCollection>[] _configure = Array.Empty<Action<IServiceCollection>>();

    public async Task<PluginHost> BuildAsync(CancellationToken ct = default)
    {
        var services = new ServiceCollection();
        foreach (var configure in _configure)
            configure(services);

        var provider = services.BuildServiceProvider(validateScopes: false); // ACQ:X

        var db = provider.GetService<IDbInitializer>();
        if (db is not null)
        {
            await db.InitializeAsync(ct).ConfigureAwait(false);
        }

        foreach (var _ in provider.GetServices<IBackgroundService>())
        {
        }

        return new PluginHost(provider);
    }
}

public sealed class XFixed
{
    private readonly Action<IServiceCollection>[] _configure = Array.Empty<Action<IServiceCollection>>();

    public async Task<PluginHost> BuildAsync(CancellationToken ct = default)
    {
        var services = new ServiceCollection();
        foreach (var configure in _configure)
            configure(services);

        var provider = services.BuildServiceProvider(validateScopes: false); // ACQ:X

        try
        {
            var db = provider.GetService<IDbInitializer>();
            if (db is not null)
            {
                await db.InitializeAsync(ct).ConfigureAwait(false);
            }

            foreach (var _ in provider.GetServices<IBackgroundService>())
            {
            }

            return new PluginHost(provider);
        }
        catch (Exception)
        {
            try
            {
                await new PluginHost(provider).DisposeAsync().ConfigureAwait(false);
            }
            catch (Exception)
            {
                // swallowed, as in the fix
            }
            throw;
        }
    }
}
