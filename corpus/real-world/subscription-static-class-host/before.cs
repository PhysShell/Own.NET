using System;

// BUG: an INSTANCE host subscribes a `this`-capturing handler to the process-lived
// static event `Console.CancelKeyPress` and never detaches it. The process-lived
// source pins this Host instance for the whole process — an OWN014 region escape.
sealed class Host
{
    int _count;

    public Host()
    {
        Console.CancelKeyPress += (s, e) => _count++;   // captures this; never -=
    }
}
