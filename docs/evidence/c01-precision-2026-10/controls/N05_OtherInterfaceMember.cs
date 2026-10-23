// N5 — mechanism negative (wrong member): Dispose calls a DIFFERENT interface member (`Pause`) of this object;
// the `-=` lives in `Detach`, which nothing on the teardown path calls. Must stay OWN001 (the edge is
// symbol-exact: only the implementation of the member actually invoked is credited).
using System;
using C01P1.Common;

namespace C01P1.N05
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

        public void Dispose() { (this as IDetachable).Pause(); }

        private void OnChanged(object? sender, EventArgs e) { }
    }
}
