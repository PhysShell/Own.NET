using System;

// NOT self-owned (P-004, the ref/out narrowing — Codex P2 on PR #29). `_bus` is
// populated by a DIFFERENT class's `ref` method — a resolution/exchange, not
// construction by THIS class — so the ref/out self-owned exemption must NOT apply:
// `_bus` may be an injected, longer-lived publisher, and suppressing the
// subscription would be a false negative (a real leak silently dropped). The
// extractor must report it (OWN001, warning: injected source). Contrast
// SelfOwnedControlParts, whose `_thumb` is built by its OWN `BuildCorner` (same
// class) and so IS exempt. Namespaced to avoid clashing with the other samples.
namespace OwnSamples.ExternalRef
{
    public sealed class ExternalRefSubscription
    {
        private Publisher _bus = null!;

        public ExternalRefSubscription()
        {
            Resolver.Resolve(ref _bus);   // external class assigns _bus (not ours to own)
            _bus.Changed += OnChanged;    // must be flagged, NOT exempted -> OWN001
        }

        private void OnChanged(object? sender, EventArgs e) { }
    }

    public sealed class Publisher { public event EventHandler? Changed; }

    public static class Resolver
    {
        public static void Resolve(ref Publisher p) => p = new Publisher();
    }
}
