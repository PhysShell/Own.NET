// N2 — mechanism negative (scope): the interface is implemented by the BASE class, which also holds the
// subscription; only the DERIVED class has Dispose. The patch credits only an implementation declared in the
// SAME class as the teardown root (intra-class, like #278), so the base-class subscription keeps its warning
// (a kept-warning worst case: at runtime this one IS released — conservative by design).
using System;
using C01P1.Common;

namespace C01P1.N02
{
    public class Base : IDetachable
    {
        protected readonly Publisher Bus;

        public Base(Publisher bus)
        {
            Bus = bus;
            Bus.Changed += OnChanged; // EXPECT before=OWN001 after=OWN001
        }

        void IDetachable.Detach() { Bus.Changed -= OnChanged; }
        void IDetachable.Pause() { }

        private void OnChanged(object? sender, EventArgs e) { }
    }

    public sealed class Derived : Base, IDisposable
    {
        public Derived(Publisher bus) : base(bus) { }

        public void Dispose() { (this as IDetachable).Detach(); }
    }
}
