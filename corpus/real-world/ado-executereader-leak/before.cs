using System.Data.Common;

// A DbDataReader returned by DbCommand.ExecuteReader() is a fresh owned IDisposable the caller
// must dispose -- dropping it leaks the reader and holds the underlying server-side cursor open
// until finalization. The command here is a borrowed parameter (the caller owns it), so the ONLY
// leak is `reader`. This is the single most common real-world ADO.NET resource leak.
static class AdoReaderLeak
{
    static int Run(DbCommand cmd)
    {
        var reader = cmd.ExecuteReader();   // fresh owned DbDataReader -> OWN001 (never disposed)
        var n = 0;
        while (reader.Read())
            n++;
        return n;                            // BUG: reader never disposed
    }
}
