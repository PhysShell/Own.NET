// Form 4c — SAFE, TARGET OF THE PATCH, other spellings of the same self-call:
// `((IDetachable)this).Detach()`, `(this as IDetachable)?.Detach()`, and an IMPLICIT (public) implementation.
// Oracle: same as 4b — the call resolves to this class's own implementation. Expected after: silent.
using System;
using C01P1.Common;

namespace C01P1.F04c
{
    public sealed class CastSpelling : IDisposable, IDetachable
    {
        private readonly Publisher _bus;

        public CastSpelling(Publisher bus)
        {
            _bus = bus;
            _bus.Changed += OnChanged; // EXPECT before=OWN001 after=none
        }

        void IDetachable.Detach() => _bus.Changed -= OnChanged;
        void IDetachable.Pause() { }

        public void Dispose() { ((IDetachable)this).Detach(); }

        private void OnChanged(object? sender, EventArgs e) { }
    }

    public sealed class ConditionalSpelling : IDisposable, IDetachable
    {
        private readonly Publisher _bus;

        public ConditionalSpelling(Publisher bus)
        {
            _bus = bus;
            _bus.Changed += OnChanged; // EXPECT before=OWN001 after=none
        }

        void IDetachable.Detach() { _bus.Changed -= OnChanged; }
        void IDetachable.Pause() { }

        public void Dispose() { (this as IDetachable)?.Detach(); }

        private void OnChanged(object? sender, EventArgs e) { }
    }

    public sealed class ImplicitImpl : IDisposable, IDetachable
    {
        private readonly Publisher _bus;

        public ImplicitImpl(Publisher bus)
        {
            _bus = bus;
            _bus.Changed += OnChanged; // EXPECT before=OWN001 after=none
        }

        public void Detach() { _bus.Changed -= OnChanged; }
        public void Pause() { }

        public void Dispose() { ((IDetachable)this).Detach(); }

        private void OnChanged(object? sender, EventArgs e) { }
    }
}
