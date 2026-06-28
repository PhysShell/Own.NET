using System;

// FIX: the host is a STATIC class — it has no instance, so the process-lived
// subscription promotes nothing (a static class is already process-lived; its state
// lives for the whole process by definition). The shutdown hook captures only
// static/local state, never a `this`. Not a leak (mined on CsvHelper's static
// `ConsoleHost`, whose `ProcessExit`/`CancelKeyPress` hooks are false positives).
static class Host
{
    static int _count;

    public static void Attach()
    {
        Console.CancelKeyPress += (s, e) => _count++;   // no instance to over-promote
    }
}
