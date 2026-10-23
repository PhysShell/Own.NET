// Form 7 — DANGEROUS: `-=` with a NEW lambda removes nothing. Delegate equality is target + method, and the two
// textually identical lambdas compile to two different methods, so the `-=` delegate never equals the stored
// one and the original subscription survives Dispose (the MAUI SwipeView.cs:147 shape, K-S1-002).
// Oracle: real retention. Own.NET: OWN001 (lambda handler, no `-=` handle). Must stay.
using System;
using C01P1.Common;

namespace C01P1.F07
{
    public sealed class Subscriber : IDisposable
    {
        private readonly Publisher _bus;
        private int _count;

        public Subscriber(Publisher bus)
        {
            _bus = bus;
            _bus.Changed += (s, e) => _count++; // EXPECT before=OWN001 after=OWN001
        }

        public void Dispose()
        {
            _bus.Changed -= (s, e) => _count++;
        }
    }
}
