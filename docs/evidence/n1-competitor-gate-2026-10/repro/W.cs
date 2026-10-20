// W: whizbang-lib/whizbang#1204, AzureServiceBusConnectionRetry.CreateClientWithRetryAsync.
using System;
using System.Threading;
using System.Threading.Tasks;
using Stubs;

namespace Repro;

public sealed class WBuggy
{
    internal Func<string, CancellationToken, Task> VerifyNamespaceReachableAsync { get; init; } = (_, _) => Task.CompletedTask;

    public async Task<ServiceBusClient> CreateClientWithRetryAsync(string connectionString, CancellationToken cancellationToken = default)
    {
        var currentDelay = TimeSpan.FromSeconds(1);
        var attempt = 0;
        while (true)
        {
            attempt++;
            cancellationToken.ThrowIfCancellationRequested();
            try
            {
                var client = new ServiceBusClient(connectionString); // ACQ:W
                await VerifyNamespaceReachableAsync(connectionString, cancellationToken).ConfigureAwait(false);
                return client;
            }
            catch (Exception ex) when (ex is ServiceBusException || ex is TimeoutException)
            {
                if (attempt > 5) throw;
                await Task.Delay(currentDelay, cancellationToken).ConfigureAwait(false);
            }
        }
    }
}

public sealed class WFixed
{
    internal Func<string, CancellationToken, Task> VerifyNamespaceReachableAsync { get; init; } = (_, _) => Task.CompletedTask;

    internal Func<string, ServiceBusClient> CreateClient { get; init; } =
        static connectionString => new ServiceBusClient(connectionString);

    public async Task<ServiceBusClient> CreateClientWithRetryAsync(string connectionString, CancellationToken cancellationToken = default)
    {
        var currentDelay = TimeSpan.FromSeconds(1);
        var attempt = 0;
        while (true)
        {
            attempt++;
            cancellationToken.ThrowIfCancellationRequested();
            try
            {
                var client = CreateClient(connectionString); // ACQ:W
                try
                {
                    await VerifyNamespaceReachableAsync(connectionString, cancellationToken).ConfigureAwait(false);
                }
                catch
                {
                    await client.DisposeAsync().ConfigureAwait(false);
                    throw;
                }
                return client;
            }
            catch (Exception ex) when (ex is ServiceBusException || ex is TimeoutException)
            {
                if (attempt > 5) throw;
                await Task.Delay(currentDelay, cancellationToken).ConfigureAwait(false);
            }
        }
    }
}
