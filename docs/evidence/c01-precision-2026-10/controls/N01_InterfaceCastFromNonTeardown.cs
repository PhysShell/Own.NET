// N1 — mechanism negative: the same `(this as IDetachable).Detach()` self-call, but from an ordinary
// method nobody proves runs at teardown. Nothing in Dispose detaches. Must stay OWN001.
using System;
using C01P1.Common;

namespace C01P1.N01
{
    public sealed class Subscriber : IDisposable, IDetachable
    {
        private readonly Publisher _bus;

        public Subscriber(Publisher bus)
        {
            _bus = bus;
            _bus.Changed += OnChanged; // EXPECT before=OWN001 after=OWN001
        }

        void IDetachable.Detach() { _bus.Changed -= OnChanged; }
        void IDetachable.Pause() { }

        public void Reset() { (this as IDetachable).Detach(); }

        public void Dispose() { }

        private void OnChanged(object? sender, EventArgs e) { }
    }
}
