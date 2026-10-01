using Npgsql;
using Weasel.Postgresql;
using Wolverine;
using Wolverine.Postgresql.Schema;
using Wolverine.Postgresql.Transport;
using Wolverine.RDBMS;
// H-29 upstream verification: the CURRENT Wolverine PostgresqlQueueSender.ScheduleRetryAsync (JasperFx/wolverine c20fb0cc), real class,
// real Npgsql / PostgreSQL 16, an incoming row present -> what is left in incoming and scheduled after the call.
var cs = "Host=/tmp/pgsc;Username=postgres;Database=postgres;Port=5432";
await using var ds = NpgsqlDataSource.Create(cs);
var transport = new PostgresqlTransport { MessageStorageSchemaName = "public", TransportSchemaName = "wolverine_queues" };
var queue = new PostgresqlQueue("retrytest", transport);
var sender = new PostgresqlQueueSender(queue, ds, null);   // the constructor PostgresqlQueue itself uses (PostgresqlQueue.cs:109)
var scheduled = queue.ScheduledTable.Identifier.ToString(); var incomingTable = $"public.{DatabaseConstants.IncomingTable}";
await using (var conn = await ds.OpenConnectionAsync())
{
    await using (var c = conn.CreateCommand()) { c.CommandText = $"create schema if not exists wolverine_queues; drop table if exists {incomingTable}; drop table if exists {scheduled}; drop table if exists {queue.QueueTable.Identifier}"; await c.ExecuteNonQueryAsync(); }
    await queue.QueueTable.ApplyChangesAsync(conn);
    await queue.ScheduledTable.ApplyChangesAsync(conn);
    await new IncomingEnvelopeTable(new DurabilitySettings(), "public").ApplyChangesAsync(conn);
    await conn.CloseAsync();
}
async Task<(long incoming, long scheduled, string execTime)> State(Guid id)
{
    await using var c = await ds.OpenConnectionAsync();
    await using var k1 = c.CreateCommand(); k1.CommandText = $"select count(*) from {incomingTable} where {DatabaseConstants.Id} = @id"; k1.Parameters.AddWithValue("id", id); var i = (long)(await k1.ExecuteScalarAsync());
    await using var k2 = c.CreateCommand(); k2.CommandText = $"select count(*) from {scheduled} where {DatabaseConstants.Id} = @id"; k2.Parameters.AddWithValue("id", id); var s = (long)(await k2.ExecuteScalarAsync());
    await using var k3 = c.CreateCommand(); k3.CommandText = $"select {DatabaseConstants.ExecutionTime}::text from {scheduled} where {DatabaseConstants.Id} = @id"; k3.Parameters.AddWithValue("id", id); var t = (await k3.ExecuteScalarAsync())?.ToString() ?? "-";
    return (i, s, t);
}
var id = Guid.NewGuid();
await using (var conn = await ds.OpenConnectionAsync())
{
    await using var c = conn.CreateCommand();
    c.CommandText = $"insert into {incomingTable} ({DatabaseConstants.Id}, {DatabaseConstants.Status}, {DatabaseConstants.OwnerId}, {DatabaseConstants.Body}, {DatabaseConstants.MessageType}) values (@id, 'Incoming', 0, @body, 'test')";
    c.Parameters.AddWithValue("id", id); c.Parameters.AddWithValue("body", new byte[] { 1, 2, 3 }); await c.ExecuteNonQueryAsync();
}
var before = await State(id); Console.WriteLine($"before: incoming={before.incoming} scheduled={before.scheduled}");
var env = new Envelope { Id = id, MessageType = "test", Data = new byte[] { 1, 2, 3 }, ContentType = "application/json", Destination = queue.Uri, ScheduledTime = DateTimeOffset.UtcNow.AddMinutes(10), DeliverBy = DateTimeOffset.UtcNow.AddHours(1) };
await sender.ScheduleRetryAsync(env, CancellationToken.None);
var after = await State(id); Console.WriteLine($"after ScheduleRetryAsync #1: incoming={after.incoming} scheduled={after.scheduled} execution_time={after.execTime}");
env.ScheduledTime = DateTimeOffset.UtcNow.AddMinutes(20);
await sender.ScheduleRetryAsync(env, CancellationToken.None);
var after2 = await State(id); Console.WriteLine($"after ScheduleRetryAsync #2 (new scheduled time): incoming={after2.incoming} scheduled={after2.scheduled} execution_time={after2.execTime} (updated by the autocommitted upsert? {after2.execTime != after.execTime})");
// pool sanity: a fresh connection from the same pool is usable (no transaction left behind on the pooled connector)
await using (var conn = await ds.OpenConnectionAsync()) { await using var c = conn.CreateCommand(); c.CommandText = "select 1"; Console.WriteLine($"pool sanity: select 1 = {await c.ExecuteScalarAsync()}"); await using var t = await conn.BeginTransactionAsync(); await t.RollbackAsync(); Console.WriteLine("pool sanity: a new transaction on a pooled connection begins and rolls back fine"); }
