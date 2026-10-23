// Form 4a — SAFE: shared publisher, the subscription is removed on the actual teardown
// (IDisposable.Dispose), same handler, same receiver. Own.NET today: released (#278) -> silent.
using System;
using C01P1.Common;

namespace C01P1.F04a
{
    public sealed class Subscriber : IDisposable
    {
        private readonly Publisher _bus;

        public Subscriber(Publisher bus)
        {
            _bus = bus;
            _bus.Changed += OnChanged; // EXPECT before=none after=none
        }

        public void Dispose()
        {
            _bus.Changed -= OnChanged;
        }

        private void OnChanged(object? sender, EventArgs e) { }
    }
}
