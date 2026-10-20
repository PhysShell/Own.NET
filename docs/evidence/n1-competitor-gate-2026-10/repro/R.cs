// R: MarimerLLC/rockbot#638, McpBridgeService.ConnectServerAsync.
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using Stubs;

namespace Repro;

public sealed class RBuggy
{
    private readonly ConcurrentDictionary<string, McpClient> _clients = new();
    private readonly ConcurrentDictionary<string, IList<string>> _serverTools = new();

    public async Task ConnectServerAsync(string name, Uri url, int maxAttempts, CancellationToken ct)
    {
        for (var attempt = 1; attempt <= maxAttempts; attempt++)
        {
            try
            {
                var transport = new HttpClientTransport(url);
                var newClient = await McpClient.CreateAsync(transport, null, cancellationToken: ct); // ACQ:R

                var tools = await newClient.ListToolsAsync(cancellationToken: ct);
                var prompts = await newClient.ListPromptsAsync(ct);

                if (_clients.TryRemove(name, out var oldClient))
                {
                    try { await oldClient.DisposeAsync(); }
                    catch { /* Best-effort cleanup */ }
                }

                _clients[name] = newClient;
                _serverTools[name] = tools;
                return;
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested)
            {
                throw;
            }
            catch (Exception)
            {
                if (attempt == maxAttempts) return;
                await Task.Delay(100 * attempt, ct);
            }
        }
    }
}

public sealed class RFixed
{
    private readonly ConcurrentDictionary<string, McpClient> _clients = new();
    private readonly ConcurrentDictionary<string, IList<string>> _serverTools = new();

    public async Task ConnectServerAsync(string name, Uri url, int maxAttempts, CancellationToken ct)
    {
        for (var attempt = 1; attempt <= maxAttempts; attempt++)
        {
            McpClient? newClient = null;
            var published = false;
            try
            {
                var transport = new HttpClientTransport(url);
                newClient = await McpClient.CreateAsync(transport, null, cancellationToken: ct); // ACQ:R

                var tools = await newClient.ListToolsAsync(cancellationToken: ct);
                var prompts = await newClient.ListPromptsAsync(ct);

                if (_clients.TryRemove(name, out var oldClient))
                {
                    await DisposeQuietlyAsync(oldClient);
                }

                _clients[name] = newClient;
                published = true;
                _serverTools[name] = tools;
                return;
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested)
            {
                throw;
            }
            catch (Exception)
            {
                if (attempt == maxAttempts) return;
                await Task.Delay(100 * attempt, ct);
            }
            finally
            {
                if (!published && newClient is not null)
                {
                    await DisposeQuietlyAsync(newClient);
                }
            }
        }
    }

    private static async Task DisposeQuietlyAsync(IAsyncDisposable disposable)
    {
        try { await disposable.DisposeAsync(); }
        catch { /* Best-effort cleanup */ }
    }
}
