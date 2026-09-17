// FIXED (synthetic conformance). The failure path also consumes the job, so
// every back-edge decreases `queue.Count`.
using System.Collections.Generic;

public sealed class JobRunner
{
    public int Drain(Queue<string> queue)
    {
        int done = 0;
        while (queue.Count > 0)
        {
            var job = queue.Peek();
            if (!TryRun(job))
            {
                queue.Dequeue();                             // discard the bad job
                continue;
            }
            queue.Dequeue();
            done++;
        }
        return done;
    }

    private static bool TryRun(string job) => job.Length > 3;
}
