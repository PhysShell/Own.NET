using System;

namespace Own.Samples;

// P-004 resolve-aware ignored-Subscribe (WPF004), mined: StackExchange.Redis ConnectionMultiplexer.Sentinel.
// A bare `x.Subscribe(...)` is a leak ONLY when the call returns an IDisposable token (the Rx
// `IObservable<T>.Subscribe()` shape). StackExchange.Redis's `ISubscriber.Subscribe(channel, handler,
// flags)` returns VOID — there is no token to leak — so it must NOT be flagged. The IDisposable-returning
// case stays flagged (DisposableSubscriber below, and MessengerViewModel.InboxViewModel).

// a void-returning Subscribe (the handler overload) -> no IDisposable token -> must be SILENT.
public sealed class VoidSubscriber
{
    public VoidSubscriber(IRedisSubscriber sub)
    {
        sub.Subscribe("+switch-master", (_, _) => { });   // returns void -> nothing to dispose -> SILENT
    }
}

// control: a Subscribe that DOES return an IDisposable token, ignored -> STILL a leak -> WARN.
public sealed class DisposableSubscriber
{
    public DisposableSubscriber(IObservableBus bus)
    {
        bus.Subscribe(_ => { });   // returns IDisposable, ignored -> WARN (resolve-aware still fires)
    }
}

// StackExchange.Redis-style: the handler overload returns void.
public interface IRedisSubscriber
{
    void Subscribe(string channel, Action<string, string> handler);
}

// Rx-style: Subscribe hands back an IDisposable unsubscribe token.
public interface IObservableBus
{
    IDisposable Subscribe(Action<object> handler);
}
