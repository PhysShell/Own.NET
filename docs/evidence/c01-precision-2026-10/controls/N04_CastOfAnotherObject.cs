// N4 — mechanism negative (wrong instance): Dispose detaches ANOTHER object (`_peer`) through the interface,
// not `this`. Even though `_peer` has the same type, its Detach() removes the PEER's subscription, not ours.
// Must stay OWN001.
using System;
using C01P1.Common;

namespace C01P1.N04
{
    public sealed class Subscriber : IDisposable, IDetachable
    {
        private readonly Publisher _bus;
        private readonly Subscriber? _peer;

        public Subscriber(Publisher bus, Subscriber? peer)
        {
            _bus = bus;
            _peer = peer;
            _bus.Changed += OnChanged; // EXPECT before=OWN001 after=OWN001
        }

        void IDetachable.Detach() { _bus.Changed -= OnChanged; }
        void IDetachable.Pause() { }

        public void Dispose() { (_peer as IDetachable)?.Detach(); }

        private void OnChanged(object? sender, EventArgs e) { }
    }
}
