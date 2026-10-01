using Npgsql;
// H-29 runtime falsifier (h29-prereg-v1.json, runtime_falsifier_frozen): what an assigned-but-never-observed BeginTransactionAsync does.
var cs = "Host=/tmp/pgsc;Username=postgres;Database=postgres;Port=5432";
await using var ds = NpgsqlDataSource.Create(cs);
await using (var c0 = await ds.OpenConnectionAsync()) { await using var cmd0 = c0.CreateCommand(); cmd0.CommandText = "drop table if exists h29_test; create table h29_test(value int)"; await cmd0.ExecuteNonQueryAsync(); }
async Task<long> Count() { await using var c = await ds.OpenConnectionAsync(); await using var k = c.CreateCommand(); k.CommandText = "select count(*) from h29_test"; return (long)(await k.ExecuteScalarAsync()); }
// F3 control: a plain insert persists
{
    await using var conn = await ds.OpenConnectionAsync();
    await using var cmd = conn.CreateCommand(); cmd.CommandText = "insert into h29_test(value) values (1)"; await cmd.ExecuteNonQueryAsync();
    await conn.CloseAsync();
}
Console.WriteLine($"F3 control: rows = {await Count()} (expected 1)");
// F1 data loss: the demanding shape (wolverine PostgresqlQueueSender.cs:119): the ValueTask is assigned and never awaited / read
{
    await using var conn = await ds.OpenConnectionAsync();
    var ignored = conn.BeginTransactionAsync();
    Console.WriteLine($"F4 completion: ignored.IsCompleted = {ignored.IsCompleted} (the state change happened inline?)");
    await using var cmd = conn.CreateCommand(); cmd.CommandText = "insert into h29_test(value) values (2)"; await cmd.ExecuteNonQueryAsync();
    await conn.CloseAsync();
}
Console.WriteLine($"F1 after the orphaned BeginTransactionAsync: rows = {await Count()} (2 = persisted, 1 = the insert was swallowed by the orphaned transaction)");
// F1b the same with a second command before close (is every later command inside the orphan?)
{
    await using var conn = await ds.OpenConnectionAsync();
    var ignored = conn.BeginTransactionAsync();
    await using var cmd = conn.CreateCommand(); cmd.CommandText = "insert into h29_test(value) values (3)"; await cmd.ExecuteNonQueryAsync();
    await using var cmd2 = conn.CreateCommand(); cmd2.CommandText = "insert into h29_test(value) values (4)"; await cmd2.ExecuteNonQueryAsync();
    await conn.CloseAsync();
}
Console.WriteLine($"F1b two inserts after the orphan: rows = {await Count()} (3 = persisted, 1 = both swallowed)");
// F2 side effect: a second BeginTransactionAsync after the orphan
{
    await using var conn = await ds.OpenConnectionAsync();
    var ignored = conn.BeginTransactionAsync();
    try { await using var tx2 = await conn.BeginTransactionAsync(); Console.WriteLine("F2 second BeginTransactionAsync = OK (no visible side effect)"); }
    catch (Exception e) { Console.WriteLine($"F2 second BeginTransactionAsync threw {e.GetType().Name}: {e.Message}"); }
}
// F5 the fix shape: awaited and disposed without commit -> rollback is explicit and expected
{
    await using var conn = await ds.OpenConnectionAsync();
    await using (var tx = await conn.BeginTransactionAsync()) { await using var cmd = conn.CreateCommand(); cmd.CommandText = "insert into h29_test(value) values (5)"; await cmd.ExecuteNonQueryAsync(); }
    await conn.CloseAsync();
}
Console.WriteLine($"F5 awaited transaction disposed without commit: rows = {await Count()} (unchanged = explicit rollback, as documented)");
// F6 the exact shape of the real site (wolverine PostgresqlQueueSender.ScheduleRetryAsync:107-125): an autocommitted delete before the try,
// the orphaned BeginTransactionAsync inside the try, one insert on the same connection, CloseAsync in finally, `await using` disposal after
{
    await using (var c1 = await ds.OpenConnectionAsync()) { await using var k1 = c1.CreateCommand(); k1.CommandText = "drop table if exists h29_incoming; create table h29_incoming(id int); insert into h29_incoming values (7)"; await k1.ExecuteNonQueryAsync(); }
    await using var conn = await ds.OpenConnectionAsync();
    await using (var del = conn.CreateCommand()) { del.CommandText = "delete from h29_incoming where id = 7"; await del.ExecuteNonQueryAsync(); }
    try
    {
        var tx = conn.BeginTransactionAsync(CancellationToken.None);
        await using var ins = conn.CreateCommand(); ins.CommandText = "insert into h29_test(value) values (6)"; await ins.ExecuteNonQueryAsync();
    }
    finally
    {
        await conn.CloseAsync();
    }
}
{
    await using var c2 = await ds.OpenConnectionAsync(); await using var k2 = c2.CreateCommand(); k2.CommandText = "select count(*) from h29_incoming"; var incoming = (long)(await k2.ExecuteScalarAsync());
    Console.WriteLine($"F6 exact site shape: incoming rows = {incoming} (0 = the autocommitted delete persisted), scheduled rows = {await Count()} (unchanged = the scheduled insert was swallowed: the message is gone from both tables)");
}
