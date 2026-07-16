// P-035 regression (arbiter round 2): a DECLARED weak-subscribe wrapper named
// `Subscribe` that returns IDisposable. The Rx dropped-token matcher must NEVER flag
// such a call, INCLUDING under `--no-event-leaks` -- where the weak-fact pass is off.
// The declaration classifies WeakBus.Subscribe as a project weak subscription
// regardless of whether event facts are emitted, so the Rx suppression is unconditional.
//
// Scanned WITH `--weak-subscribe WeakBus.Subscribe --no-event-leaks`:
//   RxCollisionSubscriber -> ZERO subscriptions (no weak fact: the pass is off; no Rx
//   fact: the declared wrapper is suppressed).
// Without the declaration, `--no-event-leaks` alone leaves the Rx token finding in
// place -- that is the misclassification the declaration (not the flag) suppresses.
using System;

namespace Own.Samples.WeakSubscribeRx
{
    public static class WeakBus
    {
        // Returns a token (IDisposable) -- the shape the Rx dropped-token matcher flags.
        public static IDisposable Subscribe(object source, Action<object> handler) => null!;
    }

    public sealed class RxCollisionSubscriber
    {
        public RxCollisionSubscriber()
        {
            WeakBus.Subscribe(this, _ => { });
        }
    }
}
