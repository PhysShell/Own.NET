using System;
using System.IO;

static class Probe3
{
    static void Sink(Stream s) { s.Dispose(); }
    static bool Ok(Stream s) { s.Dispose(); return true; }

    static void Ternary(Stream s, bool c)
    {
        int x = c ? Use(s) : 0;
    }
    static int Use(Stream s) { s.Dispose(); return 1; }

    static void ShortCircuit(Stream s, bool c)
    {
        if (c && Ok(s)) { }
    }

    static void Switch(Stream s, int k)
    {
        switch (k)
        {
            case 1: Sink(s); break;
            default: break;
        }
    }

    static void TryCatch(Stream s)
    {
        try { s.Flush(); }
        catch (IOException) { Sink(s); }
    }

    static void Loop(Stream s, int n)
    {
        for (int i = 0; i < n; i++) { Sink(s); }
    }
}
