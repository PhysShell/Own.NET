// H-28-CMD falsifier: the provider effect of not disposing a DbCommand.
//
// Run through ../run.sh (the supervisor keeps pgserver alive while dotnet runs).
// Pinned to the original H-28 evidence: net8.0, Npgsql 10.0.3,
// Microsoft.Data.Sqlite 10.0.12, PostgreSQL 16.
//
// G1 / P4: use a dedicated Npgsql command+reader for each treatment. Record Activity
// listener counts immediately after DataTable.Load(), then immediately after the selected
// Dispose call(s). No P2/P3 SQL runs between those observations. P1-P3 run separately with
// no ActivityListener, so they cannot create or overwrite the Activity being measured.
//
// G2 / P6: enumerate live native sqlite3_stmt handles with SQLitePCL.raw.sqlite3_next_stmt
// via SqliteConnection.Handle. No RSS proxy, no GC, no memory snapshot. Count at baseline,
// after ExecuteReader, after DataTable.Load/reader.Close, after reader.Dispose, after
// command.Dispose, and on a second execution of the same command.
//
// G3 is the separate production Roslyn -> OwnIR -> summaries -> core gate in ../run.sh g3.
// This project also compiles ../fx/CommandDispose.cs as part of its build.
using System.Data;
using System.Data.Common;
using System.Diagnostics;
using Microsoft.Data.Sqlite;
using Npgsql;

static class Probe
{
    // ActivityListener callbacks can run on provider threads; use Interlocked for both writes
    // and reads. The listener is installed only after P1-P3 finish.
    static int _started, _stopped;

    internal static ActivityListener NewNpgsqlListener() => new()
    {
        ShouldListenTo = source => source.Name == "Npgsql",
        Sample = (ref ActivityCreationOptions<ActivityContext> _) => ActivitySamplingResult.AllData,
        SampleUsingParentId = (ref ActivityCreationOptions<string> _) => ActivitySamplingResult.AllData,
        ActivityStarted = _ => Interlocked.Increment(ref _started),
        ActivityStopped = _ => Interlocked.Increment(ref _stopped),
    };

    static void ResetActivity()
    {
        Interlocked.Exchange(ref _started, 0);
        Interlocked.Exchange(ref _stopped, 0);
    }

    static string ActivityReport()
        => $"started={Interlocked.CompareExchange(ref _started, 0, 0)} "
         + $"stopped={Interlocked.CompareExchange(ref _stopped, 0, 0)}";

    // P1-P3 only. No ActivityListener is installed during this helper. Cleanup is unconditional
    // and happens only AFTER all reported observations, so arms do not leak objects into the
    // following run; the intended dispose flags still determine the P1-P3 observations.
    internal static List<string> Lifecycle(string name, DbConnection conn, string sql,
                                           bool disposeCommand, bool disposeReader)
    {
        var output = new List<string>();
        DbCommand command = conn.CreateCommand();
        DbDataReader reader = null;
        bool commandDisposed = false, readerDisposed = false;
        try
        {
            command.CommandText = sql;
            reader = command.ExecuteReader();
            var table = new DataTable();
            table.Load(reader);
            output.Add($"{name} P1 reader.IsClosed after Load={reader.IsClosed}; rows={table.Rows.Count}");

            if (disposeReader)
            {
                reader.Dispose();
                readerDisposed = true;
            }

            // P2 is a separate probe from P4. It deliberately executes a second command on the
            // same object; its output is never used as evidence about Activity lifecycle.
            try
            {
                command.CommandText = "select 1";
                output.Add($"{name} P2 command reuse after reader close=OK ({command.ExecuteScalar()})");
            }
            catch (Exception e)
            {
                output.Add($"{name} P2 command reuse threw {e.GetType().Name}: {e.Message}");
            }

            if (disposeCommand)
            {
                command.Dispose();
                commandDisposed = true;
            }

            // P3 is also separate from P4: a fresh command tests whether the connection remains
            // usable after the family. Its query is never in the Activity measurement.
            try
            {
                using var c2 = conn.CreateCommand();
                c2.CommandText = "select 42";
                output.Add($"{name} P3 connection usable=OK ({c2.ExecuteScalar()}); state={conn.State}");
            }
            catch (Exception e)
            {
                output.Add($"{name} P3 connection threw {e.GetType().Name}: {e.Message}");
            }
        }
        finally
        {
            if (reader is not null && !readerDisposed)
                reader.Dispose();
            if (!commandDisposed)
                command.Dispose();
        }
        return output;
    }

    // P4: this helper performs exactly ONE ExecuteReader + DataTable.Load. It records directly
    // after Load, then after reader.Dispose when requested, then after command.Dispose when
    // requested. No other query executes in this helper. In the final cleanup of a negative
    // control, disposal happens only after the snapshots were captured.
    internal static List<string> ActivityLifecycle(string name, DbConnection conn, string sql,
                                                   bool disposeReader, bool disposeCommand)
    {
        var output = new List<string>();
        ResetActivity();
        DbCommand command = conn.CreateCommand();
        DbDataReader reader = null;
        bool readerDisposed = false, commandDisposed = false;
        try
        {
            command.CommandText = sql;
            reader = command.ExecuteReader();
            var table = new DataTable();
            table.Load(reader);
            output.Add($"{name} P4 immediately after Load: {ActivityReport()} "
                     + $"reader.IsClosed={reader.IsClosed}; rows={table.Rows.Count}");

            if (disposeReader)
            {
                reader.Dispose();
                readerDisposed = true;
                output.Add($"{name} P4 immediately after reader.Dispose(): {ActivityReport()}");
            }
            if (disposeCommand)
            {
                command.Dispose();
                commandDisposed = true;
                output.Add($"{name} P4 immediately after command.Dispose(): {ActivityReport()}");
            }
        }
        finally
        {
            // For B/C/D these are containment cleanups, not measured treatment events. Their
            // callbacks are intentionally not sampled into the already-recorded output.
            if (reader is not null && !readerDisposed)
                reader.Dispose();
            if (!commandDisposed)
                command.Dispose();
        }
        return output;
    }

    // G2/P6: direct, connection-wide count of native sqlite3_stmt objects. SqliteConnection.Handle
    // is public in Microsoft.Data.Sqlite 10.0.12; sqlite3_next_stmt walks live statements without
    // preparing another query and without triggering GC/finalization.
    static int LiveSqliteStatements(SqliteConnection connection)
    {
        var db = connection.Handle ?? throw new InvalidOperationException("SqliteConnection.Handle is null");
        int count = 0;
        var statement = SQLitePCL.raw.sqlite3_next_stmt(db, null);
        while (statement is not null)
        {
            count++;
            statement = SQLitePCL.raw.sqlite3_next_stmt(db, statement);
        }
        return count;
    }

    internal static List<string> SqliteStatementLifecycle(string name,
                                                           bool disposeReader,
                                                           bool disposeCommand,
                                                           bool executeTwice = false)
    {
        var output = new List<string>();
        using var connection = new SqliteConnection("Data Source=:memory:");
        connection.Open();
        // SQLitePCLRaw disables its wrapper lookup table by default; the native walk itself
        // works, but sqlite3_next_stmt maps raw pointers back to SafeHandles through this opt-in.
        var db = connection.Handle ?? throw new InvalidOperationException("SqliteConnection.Handle is null");
        db.enable_sqlite3_next_stmt(true);
        int baseline = LiveSqliteStatements(connection);
        output.Add($"{name} P6 before query={baseline} (delta=0)");

        var command = connection.CreateCommand();
        command.CommandText = "select 1 as a union all select 2 union all select 3";
        SqliteDataReader reader = command.ExecuteReader();
        int afterExecute = LiveSqliteStatements(connection);
        output.Add($"{name} P6 after ExecuteReader={afterExecute} (delta={afterExecute - baseline})");

        var table = new DataTable();
        table.Load(reader);
        int afterLoad = LiveSqliteStatements(connection);
        output.Add($"{name} P6 after DataTable.Load/reader.Close={afterLoad} "
                 + $"(delta={afterLoad - baseline})");

        if (disposeReader)
        {
            reader.Dispose();
            int afterReaderDispose = LiveSqliteStatements(connection);
            output.Add($"{name} P6 after reader.Dispose={afterReaderDispose} "
                     + $"(delta={afterReaderDispose - baseline})");
        }
        if (disposeCommand)
        {
            command.Dispose();
            int afterCommandDispose = LiveSqliteStatements(connection);
            output.Add($"{name} P6 after command.Dispose={afterCommandDispose} "
                     + $"(delta={afterCommandDispose - baseline})");
        }

        // Re-execution has its own arm. It reuses THIS command. On its next ExecuteReader,
        // PrepareAndEnumerateStatements must finalize the first statement before preparing the
        // second; the live count should therefore remain baseline+1, not grow to baseline+2.
        if (executeTwice)
        {
            command.CommandText = "select 4 as a union all select 5";
            var reader2 = command.ExecuteReader();
            int afterSecondExecute = LiveSqliteStatements(connection);
            output.Add($"{name} P6 after second ExecuteReader={afterSecondExecute} "
                     + $"(delta={afterSecondExecute - baseline})");
            var table2 = new DataTable();
            table2.Load(reader2);
            int afterSecondLoad = LiveSqliteStatements(connection);
            output.Add($"{name} P6 after second Load={afterSecondLoad} "
                     + $"(delta={afterSecondLoad - baseline})");
            command.Dispose();
            int afterFinalDispose = LiveSqliteStatements(connection);
            output.Add($"{name} P6 after final command.Dispose={afterFinalDispose} "
                     + $"(delta={afterFinalDispose - baseline})");
        }
        else
        {
            // Unmeasured containment cleanup: preserve the measured before/after stages above.
            reader.Dispose();
            command.Dispose();
        }
        return output;
    }

    // P5: an actual Npgsql prepared statement, before and after the command's Dispose. This is
    // the direct provider experiment; the standalone psql session check is not a substitute.
    internal static (List<string> Output, int Before, int AfterPrepare, int AfterDispose)
        PreparedStatementLifecycle(DbConnection connection)
    {
        var output = new List<string>();
        int Count()
        {
            using var countCommand = connection.CreateCommand();
            countCommand.CommandText = "select count(*) from pg_prepared_statements";
            return Convert.ToInt32(countCommand.ExecuteScalar());
        }

        int before = Count();
        var command = connection.CreateCommand();
        command.CommandText = "select $1::int";
        command.Parameters.Add(new Npgsql.NpgsqlParameter { Value = 7 });
        command.Prepare();
        command.ExecuteScalar();
        int afterPrepare = Count();
        command.Dispose();
        int afterDispose = Count();
        output.Add($"Npgsql P5 pg_prepared_statements: before={before}; "
                 + $"after Prepare={afterPrepare}; after command.Dispose={afterDispose}");
        return (output, before, afterPrepare, afterDispose);
    }
}

static class Program
{
    const string Sql = "select 1 as a union all select 2 union all select 3";
    static readonly (string Name, bool Cmd, bool Rdr)[] Variants =
    {
        ("B_neither", false, false),
        ("C_reader_only", false, true),
        ("D_command_only", true, false),
        ("A_both", true, true),
    };

    static int _failures;
    static void Check(bool condition, string message)
    {
        Console.WriteLine($"{(condition ? "PASS" : "FAIL")} {message}");
        if (!condition) _failures++;
    }

    static void Main(string[] args)
    {
        var pgDsn = Environment.GetEnvironmentVariable("H28_PG_DSN");
        var mode = args.Length > 0 ? args[0] : "all";
        Console.WriteLine($"# H-28-CMD falsifier net={Environment.Version}; "
            + $"Npgsql={typeof(NpgsqlConnection).Assembly.GetName().Version}; "
            + $"Microsoft.Data.Sqlite={typeof(SqliteConnection).Assembly.GetName().Version}");

        // G2/P6: direct native statements, separate isolated in-memory connections for B/C/D/A.
        Console.WriteLine("\n## Microsoft.Data.Sqlite: direct sqlite3_next_stmt counts");
        foreach (var v in Variants)
        {
            var rows = Probe.SqliteStatementLifecycle(v.Name, disposeReader: v.Rdr,
                                                       disposeCommand: v.Cmd);
            foreach (var row in rows) Console.WriteLine(row);
            int baselineSnapshot = ReadDelta(rows, "before query", expected: 0);
            int afterExecute = ReadDelta(rows, "after ExecuteReader", expected: 1);
            int afterLoad = ReadDelta(rows, "after DataTable.Load/reader.Close", expected: 1);
            int afterReader = v.Rdr
                ? ReadDelta(rows, "after reader.Dispose", expected: 1)
                : afterLoad;
            int afterCommand = v.Cmd
                ? ReadDelta(rows, "after command.Dispose", expected: 0)
                : afterReader;
            Check(baselineSnapshot == 0 && afterExecute == 1 && afterLoad == 1
                  && afterReader == 1 && afterCommand == (v.Cmd ? 0 : 1),
                  $"SQLite {v.Name}: reader.Dispose leaves the statement; command.Dispose finalizes it");
        }
        var reuseRows = Probe.SqliteStatementLifecycle("sqlite_reuse", disposeReader: false,
                                                        disposeCommand: false, executeTwice: true);
        foreach (var row in reuseRows) Console.WriteLine(row);
        int secondExecute = ReadDelta(reuseRows, "after second ExecuteReader", expected: 1);
        int secondLoad = ReadDelta(reuseRows, "after second Load", expected: 1);
        int finalDispose = ReadDelta(reuseRows, "after final command.Dispose", expected: 0);
        Check(secondExecute == 1 && secondLoad == 1 && finalDispose == 0,
              "SQLite repeated execution replaces rather than accumulates statements");

        if (mode == "sqlite-only")
        {
            Console.WriteLine($"\n{(_failures == 0 ? "PASS" : "FAIL")} G2 SQLite-only; failures={_failures}");
            Environment.ExitCode = _failures == 0 ? 0 : 1;
            return;
        }

        if (string.IsNullOrWhiteSpace(pgDsn))
        {
            Console.Error.WriteLine("FAIL G1: H28_PG_DSN was not supplied; no PostgreSQL runtime was tested.");
            Environment.ExitCode = 2;
            return;
        }

        Console.WriteLine("\n## Npgsql: P1-P3 (ActivityListener not installed)");
        using var pg = new NpgsqlConnection(pgDsn);
        pg.Open();
        using (var versionCommand = pg.CreateCommand())
        {
            versionCommand.CommandText = "select version()";
            var version = Convert.ToString(versionCommand.ExecuteScalar());
            Console.WriteLine($"# server: {version?.Split('\n')[0]}");
        }
        foreach (var v in Variants)
            foreach (var row in Probe.Lifecycle(v.Name, pg, Sql, v.Cmd, v.Rdr))
                Console.WriteLine(row);

        Console.WriteLine("\n## Npgsql: isolated P4 Activity lifecycle");
        using (var listener = Probe.NewNpgsqlListener())
        {
            ActivitySource.AddActivityListener(listener);
            foreach (var v in Variants)
            {
                var rows = Probe.ActivityLifecycle(v.Name, pg, "select generate_series(1,3) as a",
                                                   disposeReader: v.Rdr, disposeCommand: v.Cmd);
                foreach (var row in rows) Console.WriteLine(row);
                var afterLoad = Snapshot(rows, "immediately after Load", started: 1, stopped: 0);
                bool actionsCorrect = true;
                if (v.Rdr)
                    actionsCorrect &= Snapshot(rows, "immediately after reader.Dispose()",
                                               started: 1, stopped: 1);
                if (v.Cmd)
                    actionsCorrect &= Snapshot(rows, "immediately after command.Dispose()",
                                               started: 1, stopped: v.Rdr ? 1 : 0);
                Check(afterLoad && actionsCorrect, $"Npgsql isolated Activity stages for {v.Name}");
            }
        }

        Console.WriteLine("\n## Npgsql: P5 direct prepared-statement lifecycle");
        var prepared = Probe.PreparedStatementLifecycle(pg);
        foreach (var row in prepared.Output) Console.WriteLine(row);
        Check(prepared.AfterPrepare > prepared.Before
              && prepared.AfterDispose == prepared.AfterPrepare,
              "Npgsql command.Dispose leaves the explicit prepared statement registered");
        Console.WriteLine($"\n{(_failures == 0 ? "PASS" : "FAIL")} runtime falsifier; failures={_failures}");
        Environment.ExitCode = _failures == 0 ? 0 : 1;
    }

    static int ReadDelta(List<string> rows, string stage, int expected)
    {
        var row = rows.SingleOrDefault(x => x.Contains(stage, StringComparison.Ordinal));
        if (row is null) return int.MinValue;
        var marker = "(delta=";
        int start = row.IndexOf(marker, StringComparison.Ordinal);
        if (start < 0) return int.MinValue;
        start += marker.Length;
        int end = row.IndexOf(')', start);
        if (end < 0 || !int.TryParse(row.AsSpan(start, end - start), out var delta))
            return int.MinValue;
        if (delta != expected)
            Console.WriteLine($"FAIL expected delta={expected} at {stage}, got {delta}");
        return delta;
    }

    static bool Snapshot(List<string> rows, string stage, int started, int stopped)
    {
        var row = rows.SingleOrDefault(x => x.Contains(stage, StringComparison.Ordinal));
        bool ok = row is not null && row.Contains($"started={started} stopped={stopped}",
                                                   StringComparison.Ordinal);
        if (!ok)
            Console.WriteLine($"FAIL expected Activity started={started} stopped={stopped} at {stage}; "
                            + $"observed: {row ?? "<missing snapshot>"}");
        return ok;
    }
}
