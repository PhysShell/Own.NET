using System.IO;

class Probe2
{
    bool ready;
    static void Inner(Stream s, bool keep)
    {
        if (!keep)
        {
            s.Dispose();
        }
    }
    static void Log(Stream s) { long n = s.Length; }

    // A: forward inside the positive branch
    static void InBranch(Stream s, bool keep)
    {
        if (keep) {
            Log(s);
        }
    }

    // B: same lines, forward AFTER the if
    static void AfterIf(Stream s, bool keep)
    {
        if (keep) {
        }   Log(s);
    }

    // C: wrapper forward behind an INELIGIBLE condition
    void Behind(Stream s, bool keep)
    {
        if (ready)
        {
            Inner(s, keep);
        }
    }
}
