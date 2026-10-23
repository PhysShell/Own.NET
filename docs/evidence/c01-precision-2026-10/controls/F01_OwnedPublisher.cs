// Form 1 — SAFE: the publisher is created by the subscriber and never escapes it, so it cannot
// outlive the subscriber (collectable publisher<->subscriber cycle).
// Oracle: no retention of the subscriber by anything longer-lived. Own.NET today: P-004 self-owned
// exemption (field constructed with `new`) -> silent. The patch must not change this.
using System;
using C01P1.Common;

namespace C01P1.F01
{
    public sealed class Subscriber
    {
        private readonly Publisher _own = new Publisher();

        public Subscriber()
        {
            _own.Changed += OnChanged; // EXPECT before=none after=none
        }

        private void OnChanged(object? sender, EventArgs e) { }
    }
}
