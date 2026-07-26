// Keeping the heap alive for a runtime witness — WITHOUT blocking the UI
// thread, and without depending on stdin.
//
// Two hazards live here, and the first one bit:
//
//   * `Window.Close()` finishes through the dispatcher. A hold that parks the
//     UI thread (Thread.Sleep, Console.ReadLine) freezes WPF mid-teardown, and
//     a witness attaching then sees framework book-keeping — closed windows
//     still pinned by pending dispatcher work — instead of the steady state.
//     So the hold is a DispatcherTimer: the loop keeps pumping while we wait.
//   * A CI runner's stdin is NOT a console, so a ReadLine hold falls straight
//     through and the witness attaches to nothing. The release is a file the
//     orchestrator creates, bounded by a deadline so a stray sample can never
//     wedge a job.
using System;
using System.IO;

namespace Owen.Flagship.Wpf;

internal static class Hold
{
    private const int DefaultSeconds = 300;

    public static bool Requested =>
        Environment.GetEnvironmentVariable("OWEN_FLAGSHIP_HOLD") == "1";

    public static string? StopFile =>
        Environment.GetEnvironmentVariable("OWEN_FLAGSHIP_STOP");

    public static int Seconds =>
        int.TryParse(Environment.GetEnvironmentVariable("OWEN_FLAGSHIP_HOLD_SECONDS"),
                     out int s) && s > 0 ? s : DefaultSeconds;

    /// <summary>The pid line is the orchestration contract: whoever launched
    /// this process waits for it before attaching.</summary>
    public static void Announce()
    {
        string? stop = StopFile;
        Console.WriteLine($"holding (pid {Environment.ProcessId}) — "
            + (stop is null
                ? $"exits after {Seconds}s."
                : $"create {stop} to exit, or wait {Seconds}s."));
        Console.Out.Flush();
    }

    public static bool ShouldRelease(DateTime deadlineUtc)
    {
        if (DateTime.UtcNow >= deadlineUtc) return true;
        string? stop = StopFile;
        return stop != null && File.Exists(stop);
    }
}
