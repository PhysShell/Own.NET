using System;

class Bus { public event EventHandler? Changed; }

// BUG: the watcher subscribes a `this`-capturing handler to an INJECTED bus — an
// external object of unknown, potentially longer lifetime — and never detaches it.
// The bus's handler list keeps the Watcher alive for the bus's lifetime: a real
// subscription leak (the source may outlive `this`).
sealed class Watcher
{
    readonly Bus _bus;   // injected — lifetime owned by someone else
    int _count;

    public Watcher(Bus bus)
    {
        _bus = bus;
        _bus.Changed += (s, e) => _count++;   // never -= : leak
    }
}
