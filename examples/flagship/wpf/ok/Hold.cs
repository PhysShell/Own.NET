// Keeping the heap alive for a runtime witness, without depending on stdin.
//
// The console flagship holds on `Console.ReadLine()`, which works because its
// demo script feeds it a FIFO. A CI runner's stdin is NOT a console: ReadLine
// returns null immediately, the process exits, and the witness attaches to
// nothing. So the hold here waits for a file the orchestrator creates, with a
// deadline so a stray sample can never wedge a job.
using System;
using System.IO;
using System.Threading;

namespace Owen.Flagship.Wpf;

internal static class Hold
{
    private const int DefaultSeconds = 300;

    /// <summary>With OWEN_FLAGSHIP_HOLD=1, print the pid and block until the
    /// file named by OWEN_FLAGSHIP_STOP appears (or the deadline passes).</summary>
    public static void IfAsked()
    {
        if (Environment.GetEnvironmentVariable("OWEN_FLAGSHIP_HOLD") != "1") return;

        string? stopFile = Environment.GetEnvironmentVariable("OWEN_FLAGSHIP_STOP");
        int seconds = int.TryParse(
            Environment.GetEnvironmentVariable("OWEN_FLAGSHIP_HOLD_SECONDS"), out int s) && s > 0
            ? s : DefaultSeconds;

        // The pid line is the orchestration contract: whoever launched this
        // process waits for it before attaching.
        Console.WriteLine($"holding (pid {Environment.ProcessId}) — "
            + (stopFile is null
                ? $"exits after {seconds}s."
                : $"create {stopFile} to exit, or wait {seconds}s."));
        Console.Out.Flush();

        DateTime deadline = DateTime.UtcNow.AddSeconds(seconds);
        while (DateTime.UtcNow < deadline)
        {
            if (stopFile != null && File.Exists(stopFile)) return;
            Thread.Sleep(200);
        }
    }
}
