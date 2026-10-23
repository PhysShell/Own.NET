// N6 — mechanism negative (non-context root): the interface self-call is reached only from a FINALIZER, which
// never runs while the publisher's delegate keeps the subscriber reachable (#278 explicit non-context).
// Must stay OWN001.
using System;
using C01P1.Common;

namespace C01P1.N06
{
    public sealed class Subscriber : IDetachable
    {
        private readonly Publisher _bus;

        public Subscriber(Publisher bus)
        {
            _bus = bus;
            _bus.Changed += OnChanged; // EXPECT before=OWN001 after=OWN001
        }

        ~Subscriber() { (this as IDetachable).Detach(); }

        void IDetachable.Detach() { _bus.Changed -= OnChanged; }
        void IDetachable.Pause() { }

        private void OnChanged(object? sender, EventArgs e) { }
    }
}
