using System;

class Bus { public event EventHandler? Changed; }

// FIX: the watcher now OWNS the bus — a get-only property over a field it constructs.
// The subscription is therefore a self-cycle: the Watcher, the owned Bus, and the
// handler form one object graph the GC collects together. Not a leak, even with no
// `-=` (mined on protobuf-net's CommandLineOptions, where `XsltOptions` is a get-only
// property over a constructed XsltArgumentList field and the handler captures `this`).
sealed class Watcher
{
    readonly Bus _bus = new Bus();   // constructed — owned by this
    Bus Channel => _bus;             // get-only property returning the owned field
    int _count;

    public Watcher()
    {
        Channel.Changed += (s, e) => _count++;   // self-owned source -> silent
    }
}
