using System;
using System.IO;
using Microsoft.Win32;

namespace SystemEventsLeak;

// Two leak CLASSES in one tiny, Linux-buildable program, so the cross-tool oracle
// can run Own.NET, CodeQL AND Infer# over the same code. ScreenToGif (the real
// finding) is WPF and does not build on the Linux oracle runner, so Infer# was
// skipped there; this builds on Linux, so all three tools run.
// See README.md for the expected 2x2.
public sealed class DisplayWatcher
{
    // (1) SUBSCRIPTION leak — Own.NET's class. SystemEvents is a static,
    // process-lifetime source; subscribing without ever unsubscribing pins the
    // subscriber for the life of the process. The RAII / dataflow oracles have no
    // "event subscribed, never unsubscribed" query, so they should miss this.
    public DisplayWatcher()
    {
        SystemEvents.DisplaySettingsChanged += OnDisplayChanged;
        // ...no `-=` anywhere -> leak
    }

    private void OnDisplayChanged(object? sender, EventArgs e) { }
}

public static class Program
{
    public static void Main()
    {
        _ = new DisplayWatcher();
        LeakAFile();
        LeakInTry();
        DisposeOnThrow();
    }

    // (2) DISPOSE leak — CodeQL's / Infer#'s class, and the control: a local
    // IDisposable never disposed. All three tools should flag this, which proves the
    // RAII oracles actually ran on the fixture — so a miss on (1) is a real
    // capability gap, not an empty run.
    private static void LeakAFile()
    {
        var stream = new FileStream("scratch.bin", FileMode.Create);
        stream.WriteByte(0x42);
        // ...no Dispose()/using -> resource leak
    }

    // (3) DISPOSE leak inside a TRY-METHOD — the `try`-lowering recall slice. Before
    // try/finally was lowered, Own.NET skipped any method containing a `try`, so this
    // leak was "Oracle only" (only CodeQL / Infer# caught it). Now Own.NET lowers
    // try/finally and catches it too -> it should land in "Agree" across all three.
    private static void LeakInTry()
    {
        var tried = new FileStream("scratch2.bin", FileMode.Create);
        try { tried.WriteByte(0x42); }
        catch (Exception) { /* logged, not disposed */ }
        // ...no Dispose()/using -> resource leak, now seen despite the `try`
    }

    // (4) DISPOSE-NOT-CALLED-ON-THROW — the exception-edge slice. Unlike (2)/(3), this
    // stream IS disposed; but the Dispose() sits INSIDE the try, after a may-throw call
    // (WriteByte). On the normal path it's disposed; if WriteByte throws, control jumps
    // to the catch and the Dispose is skipped -> the stream leaks on the exceptional
    // path. CodeQL has a dedicated query for exactly this (cs/dispose-not-called-on-throw,
    // and cs/local-not-disposed also models exceptional flow). Own.NET used to miss it —
    // disposed-somewhere looked balanced — until the exception-edge model put a throw
    // edge before each may-throw statement; it now flags it too -> should join (2)/(3)
    // in "Agree".
    private static void DisposeOnThrow()
    {
        var onThrow = new FileStream("scratch3.bin", FileMode.Create);
        try
        {
            onThrow.WriteByte(0x42); // may throw -> the Dispose below is skipped on that path
            onThrow.Dispose();
        }
        catch (Exception) { /* swallowed, no dispose */ }
    }
}
