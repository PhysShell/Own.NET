// P-037-X Stage 2b hostile control X2B-C5: two eligible guards in one function, one governing
// the parameter's release, the other governing an unrelated statement. R4 (G-S1 verbatim): the
// parameter elects the governing guard only -> Split(dispose, must, no); a caller's constant
// selects: `false` -> borrow (the caller disposes: clean), `true` -> consume (clean).
using System;
using System.IO;

static class X2bC5
{
    static void Mixed(Stream s, bool log, bool dispose)
    {
        if (log)
        {
            Console.WriteLine("mixed");
        }
        if (dispose)
        {
            s.Dispose();
        }
    }

    static void KeepsIt(string path)
    {
        var r = File.OpenRead(path);
        Mixed(r, true, false);
        r.Dispose();
    }

    static void HandsItOff(string path)
    {
        var r = File.OpenRead(path);
        Mixed(r, false, true);
    }
}
