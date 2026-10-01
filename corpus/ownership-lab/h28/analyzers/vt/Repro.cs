using Npgsql;
// faithful reproduction of JasperFx/wolverine PostgresqlQueueSender.ScheduleRetryAsync (PostgresqlQueueSender.cs:107-125)
public class Repro
{
    readonly NpgsqlDataSource _dataSource;
    public Repro(NpgsqlDataSource ds) { _dataSource = ds; }
    public async Task ScheduleRetryAsync(object envelope, CancellationToken cancellationToken)
    {
        await using var conn = await _dataSource.OpenConnectionAsync(cancellationToken);
        var del = conn.CreateCommand(); del.CommandText = "delete from t where id = 1"; await del.ExecuteNonQueryAsync(cancellationToken);
        try
        {
            var tx = conn.BeginTransactionAsync(cancellationToken);
            await scheduleMessageAsync(envelope, cancellationToken, conn);
        }
        finally
        {
            await conn.CloseAsync();
        }
    }
    static Task scheduleMessageAsync(object envelope, CancellationToken ct, NpgsqlConnection conn) => Task.CompletedTask;
}
public class Ide0059Controls
{
    public void C1() { var unused = 5; }                                   // IDE0059 control: a plain unused assignment
    public void C2() { var t2 = Task.CompletedTask; }                      // IDE0059 control: an unused Task-typed local
    public void C3() { var vt3 = new ValueTask<int>(5); }                  // IDE0059 control: an unused ValueTask struct local
    public void C4(NpgsqlConnection conn) { var tx = conn.BeginTransactionAsync(); }   // the orphan shape outside async / try
}
public class Ide0059Shapes
{
    public async Task C5_async_no_try(NpgsqlConnection conn) { var tx = conn.BeginTransactionAsync(); await Task.Yield(); }          // async, no try
    public void C6_sync_try_finally(NpgsqlConnection conn) { try { var tx = conn.BeginTransactionAsync(); } finally { conn.Close(); } }   // sync, try/finally
    public async Task C7_async_try_no_await_after(NpgsqlConnection conn) { try { var tx = conn.BeginTransactionAsync(); } finally { await conn.CloseAsync(); } }   // async, try, nothing awaited inside the try
    public async Task C8_async_try_await_after(NpgsqlConnection conn) { try { var tx = conn.BeginTransactionAsync(); await Task.Yield(); } finally { await conn.CloseAsync(); } }   // the exact shape: async, try, an await after the orphan
}
