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
}
