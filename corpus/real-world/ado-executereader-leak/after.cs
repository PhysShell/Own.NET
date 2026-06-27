using System.Data.Common;

// FIX: own the reader for the scope with `using`, so it is disposed on every exit path.
static class AdoReaderLeak
{
    static int Run(DbCommand cmd)
    {
        using var reader = cmd.ExecuteReader();   // disposed at scope exit -> clean
        var n = 0;
        while (reader.Read())
            n++;
        return n;
    }
}
