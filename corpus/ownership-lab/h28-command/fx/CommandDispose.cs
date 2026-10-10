// H-28-CMD fixture: the DbCommand half of the DataTable.Load(reader) family.
//
// Deliberately written against the ABSTRACT ADO.NET types (DbConnection / DbCommand /
// DbDataReader), not against Npgsql, because that is exactly what Own.NET's
// IsOwningFactory matches on (frontend/roslyn/OwnSharp.Extractor/Program.cs, the ADO.NET
// tranche: receiver implements IDbConnection, return implements IDbCommand). This makes it a
// useful source-level fixture for the provider-agnostic acquisition rule; it does NOT run the
// same C# against each provider. G1/G2 runtime checks and G3 extraction have now run for the
// pinned providers; see ../README.txt and docs/notes/h28-npgsql-command-resolution.md.
//
// G3 checks the method-specific finding anchors. To reproduce the local production path:
//   dotnet ownsharp-extract.dll --flow-locals fx/CommandDispose.cs -o cmd.facts.json
//   python -m ownlang summaries cmd.facts.json
//   python -m ownlang ownir cmd.facts.json --format sarif --verbosity verbose
//
// The producing sandbox lacked the .NET SDK/NuGet feed, so initial expectations were source
// predictions. G1/G2/G3 have since passed in PR workflow run #38048287923; G3 confirmed the
// expected extraction anchors for this file. The attached workflow artifact holds the raw facts,
// summaries, SARIF and runtime logs (see docs/notes/h28-npgsql-command-resolution.md).
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
    // G3 CONFIRMED: OWN001 on `command`; SILENT on `reader`.
    public static DataTable B_load_neither_disposed(DbConnection connection, string sql)
    {
        var command = connection.CreateCommand();
        command.CommandText = sql;
        var reader = command.ExecuteReader();

        var table = new DataTable();
        table.Load(reader);          // witnessed: closes the reader when it is the last result set
        return table;
    }

    // A: the fully-released control. G3 CONFIRMED: clean.
    public static DataTable A_load_both_disposed(DbConnection connection, string sql)
    {
        using var command = connection.CreateCommand();
        command.CommandText = sql;
        using var reader = command.ExecuteReader();

        var table = new DataTable();
        table.Load(reader);
        return table;
    }

    // C: the reader explicitly released, the command not. In Npgsql 10.0.3 source, reader
    // Dispose/DisposeAsync call Command.TraceCommandStop while public Close uses the
    // non-disposing close path. G1/P4 confirmed the isolated Activity snapshots; G3 CONFIRMED
    // OWN001 on `command`.
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

    // D: the command released after Load, the reader not (Load already closed it). For
    // Microsoft.Data.Sqlite 10.0.12, G2 observed the native statement count return to baseline
    // at command.Dispose; G3 CONFIRMED this control is clean.
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
    // owned instead of borrowed. G3 CONFIRMED: OWN001 on `command` AND OWN001 on `reader`.
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
    // G3 CONFIRMED: OWN001 on `command` only.
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

    // G: the source indicates reader cleanup sets `Command.State = CommandState.Idle`; this
    // predicts reuse is possible and that the command lifetime is not bounded by reader close.
    // P2 emits a descriptive reuse observation; G3 CONFIRMED this control is clean.
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

    // H: the prepared-statement arm. Npgsql source routes prepared-statement management through
    // the connector's PreparedStatementManager, and its reviewed command Dispose body shows no
    // explicit native-handle release or DEALLOCATE. Connector/session ownership alone does not
    // prove the command cannot issue DEALLOCATE. P5 measured the explicit statement count increase
    // after Prepare and unchanged count after Dispose in the tested session. G3 CONFIRMED the
    // extractor finding on `command`; neither result generalizes to every prepared resource.
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
    // become a candidate. G3 CONFIRMED: OWN001 on `command` only, never on `table`.
    public static DataTable I_table_is_dispose_optional(DbConnection connection, string sql)
    {
        var command = connection.CreateCommand();
        command.CommandText = sql;
        var table = new DataTable();
        table.Load(command.ExecuteReader());
        return table;
    }
}
