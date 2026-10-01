using System.Data;
using System.Data.Common;
using Microsoft.Data.Sqlite;
using Npgsql;
// H-28 runtime falsifier (h28-prereg-v1.json, runtime_falsifier_of_the_demanding_instance): what DataTable.Load(IDataReader) does to the reader.
static async Task Probe(string name, DbConnection conn, string sql1, string sql2)
{
    await conn.OpenAsync();
    var cmd = conn.CreateCommand(); cmd.CommandText = sql1;
    DbDataReader reader = await cmd.ExecuteReaderAsync();
    var table = new DataTable(); table.Load(reader);
    Console.WriteLine($"{name} rows loaded = {table.Rows.Count}");
    Console.WriteLine($"{name} F1 reader.IsClosed after Load = {reader.IsClosed}");
    try { var adv = await reader.ReadAsync(); Console.WriteLine($"{name} F2 Read after Load = {adv} (no throw); NextResult = {await reader.NextResultAsync()}"); }
    catch (Exception e) { Console.WriteLine($"{name} F2 Read after Load threw {e.GetType().Name}: {e.Message}"); }
    try { var c2 = conn.CreateCommand(); c2.CommandText = sql2; var r2 = await c2.ExecuteScalarAsync(); Console.WriteLine($"{name} F3 second command with the un-closed reader alive = OK ({r2})"); }
    catch (Exception e) { Console.WriteLine($"{name} F3 second command threw {e.GetType().Name}: {e.Message}"); }
    try { await reader.CloseAsync(); var c3 = conn.CreateCommand(); c3.CommandText = sql2; var r3 = await c3.ExecuteScalarAsync(); Console.WriteLine($"{name} F3b after reader.Close the second command = OK ({r3})"); }
    catch (Exception e) { Console.WriteLine($"{name} F3b after reader.Close threw {e.GetType().Name}: {e.Message}"); }
    // F4: the caller's connection dispose with a live reader (fresh reader)
    var cmd4 = conn.CreateCommand(); cmd4.CommandText = sql1; var reader4 = await cmd4.ExecuteReaderAsync(); var t4 = new DataTable(); t4.Load(reader4);
    await conn.DisposeAsync();
    Console.WriteLine($"{name} F4 after connection dispose: reader.IsClosed = {reader4.IsClosed}");
}
await Probe("sqlite", new SqliteConnection("Data Source=:memory:"), "select 1 as a union all select 2", "select 42");
await Probe("npgsql", new NpgsqlConnection("Host=/tmp/pgsc;Username=postgres;Database=postgres;Port=5432"), "select generate_series(1,3) as a", "select 42");
