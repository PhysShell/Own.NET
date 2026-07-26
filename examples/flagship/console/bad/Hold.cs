// Keeping the heap alive for a runtime witness.
//
// Two release mechanisms, because the two callers differ. `scripts/flagship-
// demo.sh` keeps a FIFO on stdin and releases the sample with a line — the
// default. A CI runner's stdin is NOT a console, where a ReadLine hold would
// fall straight through and the witness would attach to nothing; those callers
// set OWEN_FLAGSHIP_STOP and release the sample by creating that file. Both
// paths are bounded by a deadline, so a stray sample can never wedge a job.
using System;
using System.IO;
using System.Threading;

namespace Owen.Flagship;

internal static class Hold
{
    private const int DefaultSeconds = 300;

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
                ? "send a line to exit."
                : $"create {stopFile} to exit, or wait {seconds}s."));
        Console.Out.Flush();

        if (stopFile is null)
        {
            Console.ReadLine();
            return;
        }

        DateTime deadline = DateTime.UtcNow.AddSeconds(seconds);
        while (DateTime.UtcNow < deadline)
        {
            if (File.Exists(stopFile)) return;
            Thread.Sleep(200);
        }
    }
}
