// A consumer-style fixture for the P-035 --config plumbing, exercised through the
// composite Action (uses: ./) in action-marketplace-readiness.yml.
//
// WeakBus.Subscribe is this project's own weak-subscribe wrapper: it returns an
// IDisposable token, so WITHOUT a [weak-subscription] declaration the ignored token
// is a real finding (a dropped Rx-style subscription). WITH own.toml declaring
// "WeakBus.Subscribe", P-035 recognises it as an already-released weak subscription
// and the finding disappears. That observable difference is what proves the Action's
// `config:` input reaches the extractor.
using System;

namespace Demo.WeakConsumer
{
    public static class WeakBus
    {
        // Returns a token (IDisposable) — the shape the dropped-token check flags.
        public static IDisposable Subscribe(object source, Action<object> handler) => null!;
    }

    public sealed class Consumer
    {
        public Consumer(object source)
        {
            // Token ignored on purpose: a leak WITHOUT the declaration, an accepted
            // weak subscription WITH it.
            WeakBus.Subscribe(source, OnNext);
        }

        private void OnNext(object value) { }
    }
}
