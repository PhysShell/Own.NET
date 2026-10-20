// Stubs for third-party types used by the N1 reproductions. Each keeps the real type's disposable
// interfaces and the members the reproduced method calls; bodies are irrelevant to the analyzers.
using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;

namespace Stubs;

// Azure.Messaging.ServiceBus.ServiceBusClient : IAsyncDisposable
public class ServiceBusClient : IAsyncDisposable
{
    public ServiceBusClient(string connectionString) { }
    public ValueTask DisposeAsync() => default;
}

public class ServiceBusException : Exception { }

// ModelContextProtocol.Client.McpClient : IAsyncDisposable, created by an async factory
public abstract class McpClient : IAsyncDisposable
{
    public static Task<McpClient> CreateAsync(IClientTransport transport, object? options = null,
        CancellationToken cancellationToken = default) => throw new NotImplementedException();
    public abstract Task<IList<string>> ListToolsAsync(CancellationToken cancellationToken = default);
    public abstract Task<IList<string>> ListPromptsAsync(CancellationToken cancellationToken = default);
    public abstract ValueTask DisposeAsync();
}

public interface IClientTransport { }

public sealed class HttpClientTransport : IClientTransport
{
    public HttpClientTransport(Uri endpoint) { }
}

// RabbitMQ.Client 7: IChannel : IAsyncDisposable, IDisposable; created by IConnection.CreateChannelAsync
public interface IChannel : IAsyncDisposable, IDisposable
{
    Task BasicQosAsync(uint prefetchSize, ushort prefetchCount, bool global, CancellationToken cancellationToken = default);
    Task<string> BasicConsumeAsync(string queue, bool autoAck, CancellationToken cancellationToken = default);
    Task CloseAsync(CancellationToken cancellationToken = default);
}

public interface IConnection : IAsyncDisposable, IDisposable
{
    Task<IChannel> CreateChannelAsync(CancellationToken cancellationToken = default);
}
