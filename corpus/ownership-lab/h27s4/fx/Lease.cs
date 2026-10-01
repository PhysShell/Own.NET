using System;
using System.Data.Common;
using System.Threading.Tasks;
using Npgsql;
// H-27 step 4 fixture: one method per expected site class (the name carries the expectation).
public class Lease
{
    DbCommand _cmd; DbConnection _conn; NpgsqlConnection _nconn; DbDataReader _r;
    public DbCommand Cmd { get; set; }
    // RELEASED
    public async Task R1_using_decl(DbCommand cmd) { await using var r = await cmd.ExecuteReaderAsync(); }
    public async Task R2_using_stmt_decl(DbCommand cmd) { using (var r = await cmd.ExecuteReaderAsync()) { } }
    public async Task R3_await_using_stmt_decl_configureawait(DbCommand cmd) { await using (var r = await cmd.ExecuteReaderAsync().ConfigureAwait(false)) { } }
    public async Task R4_explicit_dispose(DbCommand cmd) { var r = await cmd.ExecuteReaderAsync(); r.Dispose(); }
    public async Task R5_explicit_close_async(DbCommand cmd) { var r = await cmd.ExecuteReaderAsync(); await r.CloseAsync(); }
    public async Task R6_try_finally(DbCommand cmd) { DbDataReader r = null; try { r = await cmd.ExecuteReaderAsync(); } finally { r?.Dispose(); } }
    public async Task R7_commit(DbConnection conn) { var t = await conn.BeginTransactionAsync(); await t.CommitAsync(); }
    public async Task R8_using_stmt_later(DbCommand cmd) { var r = await cmd.ExecuteReaderAsync(); using (r) { } }
    public async Task R9_passed_then_disposed(DbCommand cmd) { var r = await cmd.ExecuteReaderAsync(); Consume(r); r.Dispose(); }
    // RECLAIMED_IN_MEMBER
    public async Task M1_receiver_using_decl(NpgsqlConnection conn) { await using var cmd = conn.CreateCommand(); var r = await cmd.ExecuteReaderAsync(); while (await r.ReadAsync()) { } }
    public async Task M2_receiver_using_stmt(DbConnection conn) { using (var cmd = conn.CreateCommand()) { var r = await cmd.ExecuteReaderAsync(); } }
    public async Task M3_receiver_disposed_explicitly(DbConnection conn) { var cmd = conn.CreateCommand(); var r = await cmd.ExecuteReaderAsync(); cmd.Dispose(); }
    public async Task M4_passed_receiver_released(NpgsqlConnection conn) { await using var cmd = conn.CreateCommand(); var r = await cmd.ExecuteReaderAsync(); Consume(r); }
    // LEAK_CANDIDATE
    public async Task L1_parameter_receiver(DbCommand cmd) { var r = await cmd.ExecuteReaderAsync(); while (await r.ReadAsync()) { } }
    public async Task L2_field_receiver() { var t = await _conn.BeginTransactionAsync(); }
    public async Task L3_property_receiver() { var r = await Cmd.ExecuteReaderAsync(); }
    public async Task L4_receiver_stored(DbConnection conn) { var cmd = conn.CreateCommand(); _cmd = cmd; var r = await cmd.ExecuteReaderAsync(); }
    public async Task L5_assignment_sink(DbConnection conn) { DbTransaction t; t = await conn.BeginTransactionAsync(); }
    public async Task L6_cast_parameter_receiver(object cmd) { var r = await ((DbCommand)cmd).ExecuteReaderAsync(); }
    // TEMPORARY_RECEIVER
    public async Task T1_chained_receiver(DbConnection conn) { var r = await conn.CreateCommand().ExecuteReaderAsync(); }
    public async Task T2_new_receiver() { var r = await new NpgsqlCommand("select 1", _nconn).ExecuteReaderAsync(); }
    // UNCLEAR
    public async Task U1_passed_receiver_outlives(DbCommand cmd) { var r = await cmd.ExecuteReaderAsync(); Consume(r); }
    public async Task U2_local_receiver_unreleased(DbConnection conn) { var cmd = conn.CreateCommand(); var r = await cmd.ExecuteReaderAsync(); }
    public async Task<DbDataReader> U3_returned(DbCommand cmd) { var r = await cmd.ExecuteReaderAsync(); return r; }
    public async Task U4_stored(DbCommand cmd) { var r = await cmd.ExecuteReaderAsync(); _r = r; }
    public async Task U5_non_local_sink_argument(DbCommand cmd) { Consume(await cmd.ExecuteReaderAsync()); }
    public async Task U6_chained_result(DbCommand cmd) { var ok = (await cmd.ExecuteReaderAsync()).HasRows; }
    // descriptive: the sync twin, and the connection-using flag
    public void S1_sync_twin(DbCommand cmd) { var r = cmd.ExecuteReader(); }
    public async Task C1_connection_using_flag(NpgsqlDataSource ds) { await using var conn = await ds.OpenConnectionAsync(); var cmd = conn.CreateCommand(); var r = await cmd.ExecuteReaderAsync(); }
    void Consume(DbDataReader r) { }
}
