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
