using System;
using System.Collections.Generic;
using System.Data.Common;
using System.Threading;
using System.Threading.Tasks;
using Npgsql;
// H-29 fixture: orphaned awaitables and their twins; the method name carries the expectation (family / form / later references).
public class Orphan
{
    Task _kept; Stream _s = null;
    public async Task O01_B_orphan(NpgsqlConnection conn, CancellationToken ct) { var tx = conn.BeginTransactionAsync(ct); await Task.Yield(); }                               // local, B, refs 0 (PRIMARY)
    public async Task O02_A_orphan(NpgsqlCommand cmd) { var r = cmd.ExecuteReaderAsync(); await Task.Yield(); }                                                                // local, A, refs 0 (PRIMARY)
    public async Task O03_observed_later(NpgsqlConnection conn, CancellationToken ct) { var tx = conn.BeginTransactionAsync(ct); await using var t = await tx; }               // refs 1 (not a candidate)
    public void O04_stored(NpgsqlCommand cmd) { var t = cmd.ExecuteNonQueryAsync(); _kept = t; }                                                                                // refs 1
    public async Task O05_passed(NpgsqlCommand cmd) { var t = cmd.ExecuteNonQueryAsync(); await Task.WhenAll(t); }                                                             // refs 1
    public void O06_discard(NpgsqlConnection conn, CancellationToken ct) { _ = conn.BeginTransactionAsync(ct); }                                                                // discard, B
    public void O07_statement(NpgsqlConnection conn, CancellationToken ct) { conn.BeginTransactionAsync(ct); }                                                                  // statement, B
    public async Task O08_other_delay() { var d = Task.Delay(1); await Task.Yield(); }                                                                                          // local, OTHER, refs 0
    public async Task O09_other_nonquery(NpgsqlCommand cmd) { var n = cmd.ExecuteNonQueryAsync(); await Task.Yield(); }                                                        // local, OTHER, refs 0
    public async Task O10_awaited(NpgsqlCommand cmd) { var r = await cmd.ExecuteReaderAsync(); await r.DisposeAsync(); }                                                        // not an awaitable local (awaited)
    public async Task O11_B_configureawait(NpgsqlConnection conn, CancellationToken ct) { var tx = conn.BeginTransactionAsync(ct).ConfigureAwait(false); await Task.Yield(); }  // local, B via ConfigureAwait, refs 0 (PRIMARY)
    public async Task O12_in_try(NpgsqlConnection conn, CancellationToken ct) { try { var tx = conn.BeginTransactionAsync(ct); await Task.Yield(); } finally { await conn.CloseAsync(); } }   // local, B, refs 0, in_try (PRIMARY, the real shape)
    public void O13_B_sync_commit(NpgsqlTransaction t) { var c = t.CommitAsync(); }                                                                                             // local, B (non-generic Task), refs 0 (PRIMARY)
    public async Task O14_lambda(NpgsqlConnection conn, CancellationToken ct) { Func<Task> f = async () => { var tx = conn.BeginTransactionAsync(ct); await Task.Yield(); }; await f(); }   // in_lambda flag
    public async Task O15_A_stream(Stream s) { var r = s.ReadAsync(new byte[1], 0, 1); await Task.Yield(); }                                                                   // local, OTHER (int result), refs 0
    public async Task O16_using_local(NpgsqlCommand cmd) { await using var r = await cmd.ExecuteReaderAsync(); }                                                               // using local: skipped
}
