// H-28-CMD runtime falsifier: what does the ABSENCE of DbCommand.Dispose() actually cost?
//
// This is the program that was NOT runnable in the sandbox which produced the report
// (no .NET SDK, no NuGet feed -- see docs/notes/h28-npgsql-command-resolution.md section 6).
// It is written to be run as-is on a machine that has both, and every probe exists because it
// separates two hypotheses that source reading alone could not settle.
//
//   ../run.sh runtime          (starts PostgreSQL via pgserver, then dotnet run)
//   dotnet run -c Release                         # Npgsql arm skipped if no PostgreSQL
//   dotnet run -c Release -- sqlite-only          # SQLite arm only
//
// Pinned to the original H-28 evidence: net8.0, Npgsql 10.0.3, Microsoft.Data.Sqlite 10.0.12,
// PostgreSQL 16 (see h28cmd.csproj and ../README.txt).
//
// Probes
//   P1 reader.IsClosed after Load    reproduces H-28 F1 (RELEASE, not BORROW)
//   P2 command reusable after Load   "the reader bounds the command's lifetime" vs
//                                    "the reader leaves it Idle" (NpgsqlCleanup sets Idle)
//   P3 connection still usable       protocol leak vs object leak
//   P4 Activity started/stopped      THE discriminating probe for the claim that only
//                                    reader.Dispose() stops the command's Activity. Npgsql
//                                    only: its ActivitySource is named "Npgsql" and
//                                    Microsoft.Data.Sqlite has no ActivitySource at all.
//   P5 pg_prepared_statements        whether command.Dispose() releases server-side state
//   P6 RSS delta over N iterations   whether an undisposed command retains NATIVE memory
//                                    (the Microsoft.Data.Sqlite sqlite3_stmt arm)
//
// Deliberately returns List<string>, not an iterator: `yield return` is illegal inside a
// try/catch, and almost every probe here needs one.
using System.Data;
using System.Data.Common;
using System.Diagnostics;

static class Probe
{
    // ---- P4: count Activity starts and stops for Npgsql's source ---------------------
    // NpgsqlActivitySource.IsEnabled is Source.HasListeners(), so WITHOUT this listener the
    // whole tracing arm is inert (CurrentActivity stays null) and P4 would prove nothing.
    static int _started, _stopped;

    internal static readonly ActivityListener Listener = new()
    {
        ShouldListenTo = s => s.Name == "Npgsql",
        Sample = (ref ActivityCreationOptions<ActivityContext> options) => ActivitySamplingResult.AllData,
        SampleUsingParentId = (ref ActivityCreationOptions<string> options) => ActivitySamplingResult.AllData,
        ActivityStarted = _ => Interlocked.Increment(ref _started),
        ActivityStopped = _ => Interlocked.Increment(ref _stopped),
    };

    static void ResetActivity() { _started = 0; _stopped = 0; }
    static string ActivityReport() => $"started={_started} stopped={_stopped}";

    // ---- P6: process RSS. GC.GetTotalMemory is deliberately NOT used: it measures the ----
    // managed heap, and the resource in question (sqlite3_stmt) is native. One snapshot
    // proves nothing, so P6 is a DELTA over N iterations with an explicit finalization control.
    static long Rss()
    {
        GC.Collect();
        GC.WaitForPendingFinalizers();
        GC.Collect();
        return Environment.WorkingSet;
    }

    // ---- the four variants of the family; disposeCommand/disposeReader are the knobs ----
    internal static List<string> Run(string name, DbConnection conn, string sql,
                                     bool disposeCommand, bool disposeReader, bool load)
    {
        var o = new List<string>();
        ResetActivity();

        DbCommand command = conn.CreateCommand();
        command.CommandText = sql;
        DbDataReader reader = command.ExecuteReader();

        int rows = 0;
        if (load)
        {
            var table = new DataTable();
            table.Load(reader);              // BCL: Close() iff this is the last result set
            rows = table.Rows.Count;
        }
        else
        {
            while (reader.Read()) rows++;
        }

        // P1 -- the H-28 F1 reproduction
        o.Add($"{name} P1 reader.IsClosed after Load = {reader.IsClosed} (rows={rows})");

        if (disposeReader) reader.Dispose();

        // P2 -- is the command still logically usable? A model claiming the reader's lifetime
        // bounds the command's must predict a throw here.
        try
        {
            command.CommandText = "select 1";
            o.Add($"{name} P2 command reuse after the reader closed = OK ({command.ExecuteScalar()})");
        }
        catch (Exception e)
        {
            o.Add($"{name} P2 command reuse threw {e.GetType().Name}: {e.Message}");
        }

        if (disposeCommand) command.Dispose();

        // P4 -- the discriminating tracing probe (Npgsql only; 0/0 on SQLite is expected)
        o.Add($"{name} P4 Activity {ActivityReport()}");

        // P3 -- protocol leak (connection busy) or only an object leak?
        try
        {
            using var c2 = conn.CreateCommand();
            c2.CommandText = "select 42";
            o.Add($"{name} P3 connection after the family = OK ({c2.ExecuteScalar()}) state={conn.State}");
        }
        catch (Exception e)
        {
            o.Add($"{name} P3 connection threw {e.GetType().Name}: {e.Message}");
        }
        return o;
    }

    // ---- P5 -- does command.Dispose() release SERVER-SIDE prepared state? --------------
    internal static List<string> Prepared(string name, DbConnection conn, string sql)
    {
        var o = new List<string>();
        int Count()
        {
            using var c = conn.CreateCommand();
            c.CommandText = "select count(*) from pg_prepared_statements";
            return Convert.ToInt32(c.ExecuteScalar());
        }

        var cmd = conn.CreateCommand();
        cmd.CommandText = sql;
        Exception err = null;
        try { cmd.Prepare(); } catch (Exception e) { err = e; }
        if (err != null)
        {
            o.Add($"{name} P5 Prepare threw {err.GetType().Name}: {err.Message}");
            return o;
        }
        cmd.ExecuteNonQuery();
        var afterPrepare = Count();
        cmd.Dispose();                        // the arm under test
        var afterDispose = Count();
        o.Add($"{name} P5 pg_prepared_statements after Prepare={afterPrepare} "
            + $"after command.Dispose()={afterDispose} "
            + (afterDispose == afterPrepare
                 ? "-> command.Dispose() released NO server-side prepared state"
                 : "-> command.Dispose() DID release server-side prepared state"));
        return o;
    }

    // ---- P6 -- native retention over N iterations ------------------------------------
    internal static List<string> NativeRetention(string name, Func<DbConnection> open, string sql,
                                                 bool disposeCommand, int n = 20000)
    {
        var o = new List<string>();
        using var conn = open();
        conn.Open();
        // warm up, so the delta is not the provider's first-touch cost
        for (int i = 0; i < 200; i++)
        {
            var w = conn.CreateCommand(); w.CommandText = sql;
            var r = w.ExecuteReader(); var t = new DataTable(); t.Load(r);
            if (disposeCommand) w.Dispose();
        }
        var before = Rss();
        for (int i = 0; i < n; i++)
        {
            var c = conn.CreateCommand(); c.CommandText = sql;
            var r = c.ExecuteReader(); var t = new DataTable(); t.Load(r);
            if (disposeCommand) c.Dispose();
        }
        var after = Rss();
        o.Add($"{name} P6 n={n} disposeCommand={disposeCommand} "
            + $"RSS {before / 1024}KiB -> {after / 1024}KiB (delta {(after - before) / 1024}KiB)");
        return o;
    }
}

static class Program
{
    const string Sql = "select 1 as a union all select 2 union all select 3";

    static readonly (string Name, bool Cmd, bool Rdr)[] Variants =
    {
        ("B_neither",      false, false),   // the H-28 demanding instance
        ("C_reader_only",  false, true ),   // reader.Dispose(): the arm that stops the Activity
        ("D_command_only", true,  false),   // command.Dispose() after Load
        ("A_both",         true,  true ),   // fully released control
    };

    static async Task Main(string[] args)
    {
        ActivitySource.AddActivityListener(Probe.Listener);
        var pgDsn = Environment.GetEnvironmentVariable("H28_PG_DSN")
                    ?? "Host=127.0.0.1;Port=5432;Username=postgres;Password=postgres;Database=postgres";
        var mode = args.Length > 0 ? args[0] : "all";

        Console.WriteLine($"# H-28-CMD falsifier  net={Environment.Version} "
            + $"npgsql={typeof(Npgsql.NpgsqlConnection).Assembly.GetName().Version} "
            + $"sqlite={typeof(Microsoft.Data.Sqlite.SqliteConnection).Assembly.GetName().Version}");

        // ---- Microsoft.Data.Sqlite: the arm where command.Dispose() DOES matter --------
        Console.WriteLine("\n## Microsoft.Data.Sqlite (in-memory)");
        using (var conn = new Microsoft.Data.Sqlite.SqliteConnection("Data Source=:memory:"))
        {
            conn.Open();
            foreach (var v in Variants)
                foreach (var line in Probe.Run(v.Name, conn, Sql, v.Cmd, v.Rdr, load: true))
                    Console.WriteLine(line);
            foreach (var line in Probe.NativeRetention("sqlite_nodispose",
                         () => new Microsoft.Data.Sqlite.SqliteConnection("Data Source=:memory:"),
                         Sql, disposeCommand: false)) Console.WriteLine(line);
            foreach (var line in Probe.NativeRetention("sqlite_dispose",
                         () => new Microsoft.Data.Sqlite.SqliteConnection("Data Source=:memory:"),
                         Sql, disposeCommand: true)) Console.WriteLine(line);
        }
        if (mode == "sqlite-only") return;

        // ---- Npgsql: the arm where command.Dispose() releases nothing ------------------
        Console.WriteLine("\n## Npgsql (real PostgreSQL)");
        var pg = new Npgsql.NpgsqlConnection(pgDsn);
        try { await pg.OpenAsync(); }
        catch (Exception e)
        {
            Console.WriteLine($"# SKIP the Npgsql arm: cannot reach PostgreSQL at {pgDsn}: "
                            + $"{e.GetType().Name}: {e.Message}");
            Console.WriteLine("# Start one with ../run.sh runtime (pgserver) or set H28_PG_DSN.");
            return;
        }
        using (pg)
        {
            var version = (string)await pg.ExecuteScalarAsync("select version()");
            Console.WriteLine($"# server: {version.Split('\n')[0]}");
            foreach (var v in Variants)
                foreach (var line in Probe.Run(v.Name, pg, "select generate_series(1,3) as a",
                                               v.Cmd, v.Rdr, load: true))
                    Console.WriteLine(line);
            foreach (var line in Probe.Prepared("npgsql", pg, "select $1::int"))
                Console.WriteLine(line);
        }

        Console.WriteLine("\n## how to read this");
        Console.WriteLine("# P4 stopped=0 on B_neither/D_command_only and stopped=1 on C_reader_only/A_both");
        Console.WriteLine("#    => only reader.Dispose() stops the command's Activity; command.Dispose() does not.");
        Console.WriteLine("#    (P4 is 0/0 for every SQLite variant: Microsoft.Data.Sqlite has no ActivitySource.)");
        Console.WriteLine("# P2 OK everywhere => the reader does not end the command's logical lifetime.");
        Console.WriteLine("# P5 unchanged     => command.Dispose() releases no server-side prepared state.");
        Console.WriteLine("# P6 delta(nodispose) >> delta(dispose) => native retention is real on SQLite only.");
    }
}
