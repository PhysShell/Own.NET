// Form 4b — SAFE, TARGET OF THE PATCH (the MAUI iOS Shell renderer shape, ShellSectionRenderer.cs:270-306):
// shared publisher; Dispose(bool) calls THIS object's own explicit interface implementation through a
// cast, and that implementation removes the same handler from the same receiver.
//   Dispose(true) -> (this as IDetachable).Detach() -> IDetachable.Detach() { _bus.Changed -= OnChanged; }
// Oracle: C# dispatch of `(this as IDetachable).Detach()` on an instance of THIS sealed class can only reach
// the implementation declared here, so the `-=` runs whenever Dispose(true) runs — exactly as if Dispose
// contained the `-=` itself (form 4a). Own.NET today: OWN001 (the #278 closure only follows `M()`/`this.M()`).
// Expected after the patch: released -> silent. The field-null guard is the class's own state (#278 rule).
using System;
using C01P1.Common;

namespace C01P1.F04b
{
    public sealed class Subscriber : IDisposable, IDetachable
    {
        private Publisher? _bus;

        public Subscriber(Publisher bus)
        {
            _bus = bus;
            _bus.Changed += OnChanged; // EXPECT before=OWN001 after=none
        }

        void IDetachable.Detach()
        {
            if (_bus != null)
                _bus.Changed -= OnChanged;
        }

        void IDetachable.Pause() { }

        public void Dispose() => Dispose(true);

        private void Dispose(bool disposing)
        {
            if (disposing && _bus != null)
            {
                (this as IDetachable).Detach();
            }
            _bus = null;
        }

        private void OnChanged(object? sender, EventArgs e) { }
    }
}
