// P-037-X Stage 2c hostile control X2C-C4: a callee with an eligible guard whose only use of its
// parameter is an initializer-form call. With R5 the coordinate is placeable and reads Uncond(no)
// (a use is not an action; the guard governs nothing on `s`); a caller's constant selects
// nothing new; the caller that disposes is clean.
using System;
using System.IO;

static class X2cC4
{
    static int Length(Stream s)
    {
        return (int)s.Length;
    }

    static void Peek(Stream s, bool log)
    {
        var len = Length(s);
        if (log)
        {
            Console.WriteLine(len);
        }
    }

    static void Caller(string path)
    {
        var r = File.OpenRead(path);
        Peek(r, true);
        r.Dispose();
    }
}
