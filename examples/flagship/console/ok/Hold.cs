// Keeping the heap alive for a runtime witness.
//
// Three release paths, one deadline, and a null read that means nothing:
//
//   * A LINE ON STDIN — what `scripts/flagship-demo.sh` sends through its
//     FIFO. Read on a BACKGROUND thread so the deadline below still applies:
//     a blocking `Console.ReadLine()` here would wait forever if the writer
//     never sends anything, which is exactly the "forgotten sample" this
//     helper claims to prevent.
//   * THE STOP FILE (OWEN_FLAGSHIP_STOP) — for callers whose stdin is not a
//     console. Every CI runner is one of those.
//   * THE DEADLINE (OWEN_FLAGSHIP_HOLD_SECONDS, default 300) — applies to
//     every path, so a stray sample can never outlive its job. Measured with a
//     Stopwatch, not wall-clock arithmetic: `DateTime.UtcNow + seconds` is a
//     deadline the system clock can move, and a bound that a clock adjustment
//     can extend is not a bound.
//
// A NULL read is deliberately not a release: with stdin closed or redirected
// from nothing, `Console.ReadLine()` returns null immediately, and treating
// that as "the user pressed Enter" would end the hold before a witness could
// attach.
using System;
using System.Diagnostics;
using System.IO;
using System.Threading;

namespace Owen.Flagship;

internal static class Hold
{
    private const int DefaultSeconds = 300;

    private static volatile bool _lineReceived;
    private static readonly Stopwatch Elapsed = new();

    public static bool Requested =>
        Environment.GetEnvironmentVariable("OWEN_FLAGSHIP_HOLD") == "1";

    public static string? StopFile =>
        Environment.GetEnvironmentVariable("OWEN_FLAGSHIP_STOP");

    public static int Seconds =>
        int.TryParse(Environment.GetEnvironmentVariable("OWEN_FLAGSHIP_HOLD_SECONDS"),
                     out int s) && s > 0 ? s : DefaultSeconds;

    /// <summary>Hold the process until any release path fires. Safe to call
    /// unconditionally: it returns at once unless a hold was asked for.</summary>
    public static void IfAsked()
    {
        if (!Requested) return;

        Announce();
        while (!ShouldRelease()) Thread.Sleep(200);
    }

    /// <summary>The pid line is the orchestration contract: whoever launched
    /// this process waits for it before attaching. Starts the deadline clock.</summary>
    public static void Announce()
    {
        string? stop = StopFile;
        Console.WriteLine($"holding (pid {Environment.ProcessId}) — send a line to exit"
            + (stop is null ? $", or wait {Seconds}s." : $", create {stop}, or wait {Seconds}s."));
        Console.Out.Flush();
        Elapsed.Restart();
        WatchStdin();
    }

    /// <summary>True once ANY release path has fired: a line on stdin, the stop
    /// file, or the deadline.</summary>
    public static bool ShouldRelease()
    {
        if (_lineReceived || Elapsed.Elapsed >= TimeSpan.FromSeconds(Seconds)) return true;
        string? stop = StopFile;
        return stop != null && File.Exists(stop);
    }

    private static void WatchStdin()
    {
        var reader = new Thread(() =>
        {
            try
            {
                if (Console.ReadLine() != null) _lineReceived = true;
            }
            catch (IOException)
            {
                // no stdin at all — the stop file and the deadline still apply
            }
        })
        {
            IsBackground = true,   // never keeps the process alive by itself
            Name = "owen-flagship-stdin",
        };
        reader.Start();
    }
}
