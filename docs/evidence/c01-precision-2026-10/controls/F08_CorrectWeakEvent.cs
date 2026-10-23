// Form 8 — SAFE at runtime, NOT ADDRESSED by the patch (guard control): the publisher's own add/remove
// accessors keep only a WeakReference to the handler target, so the subscriber is not retained even
// without `-=`. Own.NET does not model accessor semantics (diagnosis.md §2 D), so today it warns:
// a known false positive that this iteration deliberately leaves alone. Expected: unchanged (OWN001).
using System;
using C01P1.Common;

namespace C01P1.F08
{
    public sealed class Subscriber
    {
        private readonly WeakPublisher _source;

        public Subscriber(WeakPublisher source)
        {
            _source = source;
            _source.Changed += OnChanged; // EXPECT before=OWN001 after=OWN001
        }

        private void OnChanged(object? sender, EventArgs e) { }
    }
}
