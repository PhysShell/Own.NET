// Keeping the heap alive for a runtime witness — WITHOUT blocking the UI
// thread, and without trusting stdin to exist.
//
// Three hazards live here, and the first one bit:
//
//   * `Window.Close()` finishes through the dispatcher. A hold that parks the
//     UI thread (Thread.Sleep, Console.ReadLine) freezes WPF mid-teardown, and
//     a witness attaching then sees framework book-keeping — closed windows
//     still pinned by pending dispatcher work — instead of the steady state.
//     So the release is polled from a DispatcherTimer and stdin is read on a
//     BACKGROUND thread: the message loop never stops pumping.
//   * A CI runner's stdin is NOT a console. `Console.ReadLine()` returns null
//     there immediately, so a null read is deliberately NOT a release signal —
//     otherwise the sample would exit before the witness could attach. Only an
//     actual line counts.
//   * Any hold can be forgotten. The deadline applies to every release path,
//     so a stray sample can never outlive its job — and it is measured with a
//     Stopwatch, not wall-clock arithmetic: a bound that a system-clock
//     adjustment can extend is not a bound.
using System;
using System.Diagnostics;
using System.IO;
using System.Threading;

namespace Owen.Flagship.Wpf;

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

    /// <summary>Print the pid line — the orchestration contract: whoever
    /// launched this process waits for it before attaching — start the
    /// deadline clock, and start watching stdin for the interactive
    /// release.</summary>
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
                // null = stdin is closed or redirected from nothing (every CI
                // runner). That is not a release; the deadline and the stop
                // file cover those callers.
                if (Console.ReadLine() != null) _lineReceived = true;
            }
            catch (IOException)
            {
                // no stdin at all — same story
            }
        })
        {
            IsBackground = true,   // never keeps the process alive by itself
            Name = "owen-flagship-stdin",
        };
        reader.Start();
    }
}
