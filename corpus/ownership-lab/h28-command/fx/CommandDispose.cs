// H-28-CMD fixture: the DbCommand half of the DataTable.Load(reader) family.
//
// Deliberately written against the ABSTRACT ADO.NET types (DbConnection / DbCommand /
// DbDataReader), not against Npgsql, because that is exactly what Own.NET's
// IsOwningFactory matches on (frontend/roslyn/OwnSharp.Extractor/Program.cs, the ADO.NET
// tranche: receiver implements IDbConnection, return implements IDbCommand). The fixture
// therefore shows the analyzer's verdict for EVERY provider at once -- which is the point:
// the runtime semantics are NOT the same for every provider (see ../README.txt and
// docs/notes/h28-npgsql-command-resolution.md).
//
// The method name carries the expectation. Run with the flow-locals default:
//   dotnet ownsharp-extract.dll --flow-locals fx/CommandDispose.cs -o cmd.facts.json
//   python -m ownlang ownir cmd.facts.json
//
// NOT EXECUTED IN THE SANDBOX THAT PRODUCED THIS COMMIT: no .NET SDK and no NuGet feed are
// reachable there (see docs/notes/h28-npgsql-command-resolution.md section 3). The
// expectations below are derived by source reading of the extractor at this commit, with
// line citations, and are marked PREDICTED until this file has been through a real build.
using System.Data;
using System.Data.Common;

public static class CommandDispose
{
    // ---- the H-28 demanding instance and its three nearest neighbours -------------

    // B: victor-wiki/DatabaseManager DbInterpreter.GetDataTableAsync:699 verbatim in shape.
    // The reader's obligation is untracked by the argument-escape rule at `table.Load(reader)`
    // (Program.cs, escapedLocals: `idn.Parent is ArgumentSyntax && !poolBuffers && !consumedArg
    // && !IsAdoptedArgOfBoundedWrapper`). The command is NOT an argument anywhere, so it stays
    // tracked and unreleased.
    // PREDICTED: OWN001 on `command`; SILENT on `reader`.
    public static DataTable B_load_neither_disposed(DbConnection connection, string sql)
    {
        var command = connection.CreateCommand();
        command.CommandText = sql;
        var reader = command.ExecuteReader();

        var table = new DataTable();
        table.Load(reader);          // witnessed: closes the reader when it is the last result set
        return table;
    }

    // A: the fully-released control. PREDICTED: clean.
    public static DataTable A_load_both_disposed(DbConnection connection, string sql)
    {
        using var command = connection.CreateCommand();
        command.CommandText = sql;
        using var reader = command.ExecuteReader();

        var table = new DataTable();
        table.Load(reader);
        return table;
    }

    // C: the reader explicitly released, the command not. This is the arm that matters for
    // Npgsql tracing: reader.Dispose() is the ONLY thing that stops the command's Activity
    // (NpgsqlDataReader.Dispose -> Command.TraceCommandStop; NpgsqlDataReader.Close does not).
    // PREDICTED: OWN001 on `command`.
    public static DataTable C_reader_disposed_command_not(DbConnection connection, string sql)
    {
        var command = connection.CreateCommand();
        command.CommandText = sql;
        var reader = command.ExecuteReader();

        var table = new DataTable();
        table.Load(reader);
        reader.Dispose();
        return table;
    }

    // D: the command released after Load, the reader not (Load already closed it).
    // For Microsoft.Data.Sqlite this is the ONLY variant in the family that releases the
    // native sqlite3_stmt handles at a deterministic point. PREDICTED: clean.
    public static DataTable D_command_disposed_after_load(DbConnection connection, string sql)
    {
        var command = connection.CreateCommand();
        command.CommandText = sql;
        var reader = command.ExecuteReader();

        var table = new DataTable();
        table.Load(reader);
        command.Dispose();
        return table;
    }

    // ---- controls that pin the two rules the prediction rests on -------------------

    // E: no DataTable.Load at all -- the reader obligation is never handed to an argument, so
    // it stays tracked. This is corpus/real-world/ado-executereader-leak with the command
    // owned instead of borrowed. PREDICTED: OWN001 on `command` AND OWN001 on `reader`.
    // If E reports only one of the two, the escape rule -- not the acquire rule -- is what
    // silenced the reader in B.
    public static int E_no_load_both_leak(DbConnection connection, string sql)
    {
        var command = connection.CreateCommand();
        command.CommandText = sql;
        var reader = command.ExecuteReader();
        var n = 0;
        while (reader.Read())
            n++;
        return n;
    }

    // F: the reader released by an explicit Close() instead of an argument pass.
    // Program.cs credits Close/Dispose/DisposeAsync as a release, so this isolates
    // "released by a call the analyzer recognises" from "released by a callee it does not".
    // PREDICTED: OWN001 on `command` only.
    public static int F_reader_closed_command_not(DbConnection connection, string sql)
    {
        var command = connection.CreateCommand();
        command.CommandText = sql;
        var reader = command.ExecuteReader();
        var n = 0;
        while (reader.Read())
            n++;
        reader.Close();
        return n;
    }

    // G: the command is still logically usable after the reader closes. NpgsqlDataReader
    // .Cleanup sets `Command.State = CommandState.Idle`, so reuse is legitimate -- the
    // command's lifetime is NOT bounded by the reader's. A model that treated reader close
    // as ending the command would mispredict this. PREDICTED: clean.
    public static int G_command_reused_after_reader_closed(DbConnection connection, string sql)
    {
        using var command = connection.CreateCommand();
        command.CommandText = sql;
        using (var reader = command.ExecuteReader())
        {
            var t = new DataTable();
            t.Load(reader);
        }
        return command.ExecuteNonQuery();     // legal: the reader's Cleanup left it Idle
    }

    // H: the prepared-statement arm. Server-side prepared state is the one resource in this
    // family whose lifetime is NOT the command's: Npgsql registers it on the CONNECTOR
    // (NpgsqlConnector.PreparedStatementManager), and NpgsqlCommand.Dispose never issues a
    // DEALLOCATE. So disposing the command does not release it, and not disposing the command
    // does not retain it. PREDICTED: OWN001 on `command` -- a finding whose fix would not
    // change any server-side state.
    public static int H_prepared_command_not_disposed(DbConnection connection, string sql)
    {
        var command = connection.CreateCommand();
        command.CommandText = sql;
        command.Prepare();
        var n = command.ExecuteNonQuery();
        return n;
    }

    // I: the dispose-optional control. DataTable IS IDisposable but Program.cs's
    // IsDisposeOptional exempts System.Data.DataTable/DataSet/DataView, so `table` must not
    // become a candidate. Proves the OWN001 in B is about the command, not the table.
    // PREDICTED: OWN001 on `command` only, never on `table`.
    public static DataTable I_table_is_dispose_optional(DbConnection connection, string sql)
    {
        var command = connection.CreateCommand();
        command.CommandText = sql;
        var table = new DataTable();
        table.Load(command.ExecuteReader());
        return table;
    }
}
