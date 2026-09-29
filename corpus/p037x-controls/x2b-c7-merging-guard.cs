// P-037-X Stage 2b hostile control X2B-C7 (added AFTER the first R4 implementation was observed
// to over-elect: recorded as such in the Stage-2b evidence). An eligible guard whose branches
// MERGE before the parameter's action does not govern it (G-S1: an enclosing `if`/`else`, or a
// literal-guarded early `return` preceding the action — nothing else). Here `log` merges and
// `dispose` encloses the release: the coordinate must elect `dispose` alone, never Conflict.
using System;
using System.IO;

static class X2bC7
{
    static void Merged(Stream s, bool log, bool dispose)
    {
        if (log)
        {
            Console.WriteLine("before");
        }
        else
        {
            Console.WriteLine("quiet");
        }
        if (dispose)
        {
            s.Dispose();
        }
    }

    static void Caller(string path)
    {
        var r = File.OpenRead(path);
        Merged(r, true, false);
        r.Dispose();
    }
}
