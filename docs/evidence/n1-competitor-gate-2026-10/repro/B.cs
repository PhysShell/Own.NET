// B: Wizard-Software/BareWire#73, RabbitMqTransportAdapter.ConsumeAsync (an async iterator).
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Runtime.CompilerServices;
using System.Threading;
using System.Threading.Tasks;
using Stubs;

namespace Repro;

public sealed class BBuggy
{
    private IConnection? _connection;
    private readonly ConcurrentDictionary<string, IChannel> _activeConsumerChannels = new();

    public async IAsyncEnumerable<string> ConsumeAsync(string endpointName, ushort prefetch,
        [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        IChannel consumerChannel = await _connection!.CreateChannelAsync(cancellationToken).ConfigureAwait(false); // ACQ:B

        await consumerChannel.BasicQosAsync(prefetchSize: 0, prefetchCount: prefetch, global: false,
            cancellationToken: cancellationToken).ConfigureAwait(false);

        string consumerChannelId = Guid.NewGuid().ToString("N");
        _activeConsumerChannels[consumerChannelId] = consumerChannel;

        string assignedTag;
        try
        {
            assignedTag = await consumerChannel.BasicConsumeAsync(endpointName, autoAck: false, cancellationToken)
                .ConfigureAwait(false);
        }
        catch
        {
            _activeConsumerChannels.TryRemove(consumerChannelId, out _);
            throw;
        }

        yield return assignedTag;
    }
}

public sealed class BFixed
{
    private IConnection? _connection;
    private readonly ConcurrentDictionary<string, IChannel> _activeConsumerChannels = new();

    public async IAsyncEnumerable<string> ConsumeAsync(string endpointName, ushort prefetch,
        [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        IChannel consumerChannel = await _connection!.CreateChannelAsync(cancellationToken).ConfigureAwait(false); // ACQ:B

        string consumerChannelId = Guid.NewGuid().ToString("N");
        _activeConsumerChannels[consumerChannelId] = consumerChannel;

        string assignedTag;
        try
        {
            await consumerChannel.BasicQosAsync(prefetchSize: 0, prefetchCount: prefetch, global: false,
                cancellationToken: cancellationToken).ConfigureAwait(false);

            assignedTag = await consumerChannel.BasicConsumeAsync(endpointName, autoAck: false, cancellationToken)
                .ConfigureAwait(false);
        }
        catch
        {
            await ReleaseConsumerChannelSafeAsync(consumerChannelId).ConfigureAwait(false);
            throw;
        }

        yield return assignedTag;
    }

    private async Task ReleaseConsumerChannelSafeAsync(string channelId)
    {
        if (_activeConsumerChannels.TryRemove(channelId, out IChannel? channel))
        {
            try { await channel.CloseAsync().ConfigureAwait(false); } catch { }
            await channel.DisposeAsync().ConfigureAwait(false);
        }
    }
}
