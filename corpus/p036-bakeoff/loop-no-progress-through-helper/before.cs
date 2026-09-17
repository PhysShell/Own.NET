// BUGGY (synthetic conformance, #275 — consume-or-exit loop progress through a
// helper). `queue.Count` controls the loop; when `TryRun` returns false the
// path `continue`s to the header without dequeuing: the same job is retried
// forever. Only an outcome-sensitive summary of `TryRun` (false => Count
// unchanged) plus the loop's own back-edge analysis can see it.
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
                continue;                                    // no progress on this path
            queue.Dequeue();
            done++;
        }
        return done;
    }

    private static bool TryRun(string job) => job.Length > 3;
}
