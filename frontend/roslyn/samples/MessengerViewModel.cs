using System;

namespace WpfApp;

// The result of Subscribe(...) is an IDisposable token; here it is ignored, so
// the subscription is never disposed and leaks. The core reports OWN001
// [resource: subscription token] at the call.
public sealed class InboxViewModel
{
    public InboxViewModel(IMessenger messenger)
    {
        messenger.Subscribe(OnMessage);   // result ignored => leak
    }

    private void OnMessage(object msg) { }
}

// The token is captured in a field and disposed on teardown — not flagged.
public sealed class CleanInboxViewModel : IDisposable
{
    private readonly IDisposable _sub;

    public CleanInboxViewModel(IMessenger messenger)
    {
        _sub = messenger.Subscribe(OnMessage);
    }

    private void OnMessage(object msg) { }

    public void Dispose() => _sub.Dispose();
}

public interface IMessenger
{
    IDisposable Subscribe(Action<object> handler);
}
