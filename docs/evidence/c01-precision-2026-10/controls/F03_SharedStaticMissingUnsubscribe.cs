// Form 3 — DANGEROUS: shared process-lived publisher (static), subscription with no unsubscribe at
// all; the subscriber even has a Dispose, but it does not detach.
// Oracle: real retention for the process lifetime. Own.NET: OWN014 (static source). Must stay.
using System;
using C01P1.Common;

namespace C01P1.F03
{
    public sealed class Subscriber : IDisposable
    {
        public Subscriber()
        {
            Hub.Shared.Changed += OnChanged; // EXPECT before=OWN014 after=OWN014
        }

        public void Dispose() { }

        private void OnChanged(object? sender, EventArgs e) { }
    }
}
