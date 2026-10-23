// Form 2 — DANGEROUS: one publisher shared by many short-lived subscribers and outliving them;
// nothing ever unsubscribes. Every Subscriber stays reachable from the shared publisher.
// Oracle: real retention (the Registry keeps the publisher for the process; views come and go).
// Own.NET: OWN001 injected (source is a ctor parameter). Must stay.
using System;
using C01P1.Common;

namespace C01P1.F02
{
    public static class Registry
    {
        public static readonly Publisher Bus = new Publisher();
        public static Subscriber Open() => new Subscriber(Bus);
    }

    public sealed class Subscriber
    {
        private readonly Publisher _bus;

        public Subscriber(Publisher bus)
        {
            _bus = bus;
            _bus.Changed += OnChanged; // EXPECT before=OWN001 after=OWN001
        }

        private void OnChanged(object? sender, EventArgs e) { }
    }
}
