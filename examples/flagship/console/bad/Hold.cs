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
//     every path, so a stray sample can never outlive its job.
//
// A NULL read is deliberately not a release: with stdin closed or redirected
// from nothing, `Console.ReadLine()` returns null immediately, and treating
// that as "the user pressed Enter" would end the hold before a witness could
// attach.
using System;
using System.IO;
using System.Threading;

namespace Owen.Flagship;

internal static class Hold
{
    private const int DefaultSeconds = 300;

    private static volatile bool _lineReceived;

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
        DateTime deadline = DateTime.UtcNow.AddSeconds(Seconds);
        while (!ShouldRelease(deadline)) Thread.Sleep(200);
    }

    /// <summary>The pid line is the orchestration contract: whoever launched
    /// this process waits for it before attaching.</summary>
    public static void Announce()
    {
        string? stop = StopFile;
        Console.WriteLine($"holding (pid {Environment.ProcessId}) — send a line to exit"
            + (stop is null ? $", or wait {Seconds}s." : $", create {stop}, or wait {Seconds}s."));
        Console.Out.Flush();
        WatchStdin();
    }

    public static bool ShouldRelease(DateTime deadlineUtc)
    {
        if (_lineReceived || DateTime.UtcNow >= deadlineUtc) return true;
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
