// N3 — mechanism negative (caller-controlled skip, #278 rule 2 / #305): the interface self-call sits under a
// parameter guard, so whether it runs is the caller's choice.
//   (a) only on the finalizer branch of Dispose(bool): `if (!disposing) (this as IDetachable).Detach();`
//   (b) Dispose() -> Cleanup(keep: true) -> `if (!keep) ((IDetachable)this).Detach();`
// Both must stay OWN001 — the new edge must not be weaker than the existing release-site guard rule.
using System;
using C01P1.Common;

namespace C01P1.N03
{
    public sealed class FinalizerBranch : IDisposable, IDetachable
    {
        private readonly Publisher _bus;

        public FinalizerBranch(Publisher bus)
        {
            _bus = bus;
            _bus.Changed += OnChanged; // EXPECT before=OWN001 after=OWN001
        }

        void IDetachable.Detach() { _bus.Changed -= OnChanged; }
        void IDetachable.Pause() { }

        public void Dispose() => Dispose(true);

        private void Dispose(bool disposing)
        {
            if (!disposing)
                (this as IDetachable).Detach();
        }

        private void OnChanged(object? sender, EventArgs e) { }
    }

    public sealed class CallerChosen : IDisposable, IDetachable
    {
        private readonly Publisher _bus;

        public CallerChosen(Publisher bus)
        {
            _bus = bus;
            _bus.Changed += OnChanged; // EXPECT before=OWN001 after=OWN001
        }

        void IDetachable.Detach() { _bus.Changed -= OnChanged; }
        void IDetachable.Pause() { }

        public void Dispose() { Cleanup(keep: true); }

        private void Cleanup(bool keep)
        {
            if (!keep)
                ((IDetachable)this).Detach();
        }

        private void OnChanged(object? sender, EventArgs e) { }
    }
}
