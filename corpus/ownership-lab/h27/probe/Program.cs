// H-27 owned-handle (lease) semantics: the frozen runtime probe P1-P6 (h26b-h27-prereg-v1.json) on
// NpgsqlConnection.BeginTransactionAsync and NpgsqlCommand.ExecuteReaderAsync against the local PostgreSQL.
// Each probe prints one JSON line; nothing is interpreted here.
using System.Text.Json;
using Npgsql;
const string CS = "Host=/tmp/pgsc;Username=postgres;Database=postgres;Port=5432";
string J(object o) => JsonSerializer.Serialize(o);
string Err(Exception e) => e.GetType().Name + ": " + e.Message.Split('\n')[0];
async Task<NpgsqlConnection> Open() { var c = new NpgsqlConnection(CS); await c.OpenAsync(); return c; }
await using (var c0 = await Open()) { await using var cmd0 = new NpgsqlCommand("CREATE TABLE IF NOT EXISTS h27 (id int); INSERT INTO h27 VALUES (1),(2)", c0); await cmd0.ExecuteNonQueryAsync(); }

// ---------------- transactions: NpgsqlConnection.BeginTransactionAsync ----------------
{
    // P1 simultaneous
    await using var c = await Open(); object r;
    try { var t1 = await c.BeginTransactionAsync(); try { var t2 = await c.BeginTransactionAsync(); r = new { api = "BeginTransactionAsync", probe = "P1_simultaneous", result = "second handle returned", same_identity = ReferenceEquals(t1, t2) }; await t1.DisposeAsync(); } catch (Exception e) { r = new { api = "BeginTransactionAsync", probe = "P1_simultaneous", result = "throws", error = Err(e) }; await t1.DisposeAsync(); } }
    catch (Exception e) { r = new { api = "BeginTransactionAsync", probe = "P1_simultaneous", result = "setup-error", error = Err(e) }; }
    Console.WriteLine(J(r));
}
{
    // P2 sequential after release; P3 use after release
    await using var c = await Open();
    var t1 = await c.BeginTransactionAsync(); await t1.DisposeAsync();
    var t2 = await c.BeginTransactionAsync();
    string usable; try { await using var cmd = new NpgsqlCommand("SELECT 1", c, t2); await cmd.ExecuteScalarAsync(); usable = "usable"; } catch (Exception e) { usable = "unusable: " + Err(e); }
    Console.WriteLine(J(new { api = "BeginTransactionAsync", probe = "P2_sequential_after_release", same_identity = ReferenceEquals(t1, t2), second_handle = usable }));
    string p3; try { await t1.CommitAsync(); p3 = "commit on released handle WORKS"; } catch (Exception e) { p3 = "throws: " + Err(e); }
    string p3b; try { await using var cmd = new NpgsqlCommand("SELECT 1", c, t1); await cmd.ExecuteScalarAsync(); p3b = "command with released handle WORKS"; } catch (Exception e) { p3b = "throws: " + Err(e); }
    Console.WriteLine(J(new { api = "BeginTransactionAsync", probe = "P3_use_after_release", commit_on_released = p3, command_with_released = p3b, note = "t1 released by DisposeAsync; t2 live at this point" }));
    await t2.DisposeAsync();
}
{
    // P4 release surface
    await using var c = await Open(); var outs = new List<object>();
    foreach (var how in new[] { "DisposeAsync", "Dispose", "CommitAsync", "RollbackAsync" })
    {
        var t = await c.BeginTransactionAsync();
        try { switch (how) { case "DisposeAsync": await t.DisposeAsync(); break; case "Dispose": t.Dispose(); break; case "CommitAsync": await t.CommitAsync(); break; case "RollbackAsync": await t.RollbackAsync(); break; } } catch (Exception e) { outs.Add(new { how, error = Err(e) }); continue; }
        string next; try { var t2 = await c.BeginTransactionAsync(); next = "next acquisition OK"; await t2.DisposeAsync(); } catch (Exception e) { next = "next acquisition throws: " + Err(e); }
        outs.Add(new { how, ends_obligation = next });
    }
    Console.WriteLine(J(new { api = "BeginTransactionAsync", probe = "P4_release_surface", results = outs }));
}
{
    // P5 receiver reclaims
    var c = await Open(); var t = await c.BeginTransactionAsync(); await c.CloseAsync();
    string after; try { await using var cmd = new NpgsqlCommand("SELECT 1", c, t); await cmd.ExecuteScalarAsync(); after = "handle usable after receiver closed"; } catch (Exception e) { after = "handle unusable after receiver closed: " + Err(e); }
    string disp; try { await t.DisposeAsync(); disp = "DisposeAsync after receiver close OK"; } catch (Exception e) { disp = "DisposeAsync after receiver close throws: " + Err(e); }
    Console.WriteLine(J(new { api = "BeginTransactionAsync", probe = "P5_receiver_reclaims", after, disp })); await c.DisposeAsync();
}
{
    // P6 disposal mandatory: acquire, do NOT release, run another operation / another acquisition
    await using var c = await Open(); var t = await c.BeginTransactionAsync();
    string op; try { await using var cmd = new NpgsqlCommand("SELECT 1", c); await cmd.ExecuteScalarAsync(); op = "another command on the receiver WORKS (runs inside the open transaction)"; } catch (Exception e) { op = "another command throws: " + Err(e); }
    string acq; try { var t2 = await c.BeginTransactionAsync(); acq = "second acquisition WORKS"; await t2.DisposeAsync(); } catch (Exception e) { acq = "second acquisition throws: " + Err(e); }
    string poolReturn; try { await c.CloseAsync(); poolReturn = "receiver close with a live transaction OK (rolled back on return to pool)"; } catch (Exception e) { poolReturn = "receiver close throws: " + Err(e); }
    Console.WriteLine(J(new { api = "BeginTransactionAsync", probe = "P6_disposal_mandatory", another_operation = op, second_acquisition = acq, receiver_close = poolReturn }));
}

// ---------------- readers: NpgsqlCommand.ExecuteReaderAsync ----------------
{
    // P1 simultaneous
    await using var c = await Open(); await using var cmd = new NpgsqlCommand("SELECT id FROM h27", c); object r;
    try { var r1 = await cmd.ExecuteReaderAsync(); try { var r2 = await cmd.ExecuteReaderAsync(); r = new { api = "ExecuteReaderAsync", probe = "P1_simultaneous", result = "second handle returned", same_identity = ReferenceEquals(r1, r2) }; await r1.DisposeAsync(); } catch (Exception e) { r = new { api = "ExecuteReaderAsync", probe = "P1_simultaneous", result = "throws", error = Err(e) }; await r1.DisposeAsync(); } }
    catch (Exception e) { r = new { api = "ExecuteReaderAsync", probe = "P1_simultaneous", result = "setup-error", error = Err(e) }; }
    Console.WriteLine(J(r));
}
{
    // P2 / P3
    await using var c = await Open(); await using var cmd = new NpgsqlCommand("SELECT id FROM h27", c);
    var r1 = await cmd.ExecuteReaderAsync(); await r1.ReadAsync(); await r1.DisposeAsync();
    var r2 = await cmd.ExecuteReaderAsync(); string usable; try { await r2.ReadAsync(); usable = "usable"; } catch (Exception e) { usable = "unusable: " + Err(e); }
    Console.WriteLine(J(new { api = "ExecuteReaderAsync", probe = "P2_sequential_after_release", same_identity = ReferenceEquals(r1, r2), second_handle = usable }));
    string p3; try { var ok = await r1.ReadAsync(); p3 = "ReadAsync on released handle WORKS (returned " + ok + "; the identity is live again as r2)"; } catch (Exception e) { p3 = "throws: " + Err(e); }
    Console.WriteLine(J(new { api = "ExecuteReaderAsync", probe = "P3_use_after_release", read_on_released = p3, note = "r1 and r2 identity equality decides what this measures" }));
    await r2.DisposeAsync();
}
{
    // P4 release surface
    await using var c = await Open(); var outs = new List<object>();
    foreach (var how in new[] { "DisposeAsync", "Dispose", "CloseAsync", "exhaust" })
    {
        await using var cmd = new NpgsqlCommand("SELECT id FROM h27", c); var rd = await cmd.ExecuteReaderAsync();
        try { switch (how) { case "DisposeAsync": await rd.DisposeAsync(); break; case "Dispose": rd.Dispose(); break; case "CloseAsync": await rd.CloseAsync(); break; case "exhaust": while (await rd.ReadAsync()) { } while (await rd.NextResultAsync()) { } break; } } catch (Exception e) { outs.Add(new { how, error = Err(e) }); continue; }
        string next; try { await using var cmd2 = new NpgsqlCommand("SELECT 1", c); await cmd2.ExecuteScalarAsync(); next = "next operation on the connection OK"; } catch (Exception e) { next = "next operation throws: " + Err(e); }
        outs.Add(new { how, ends_obligation = next }); if (how == "exhaust") await rd.DisposeAsync();
    }
    Console.WriteLine(J(new { api = "ExecuteReaderAsync", probe = "P4_release_surface", results = outs }));
}
{
    // P5 receiver reclaims: dispose the command while the reader is live; close the connection while the reader is live
    await using var c = await Open(); var cmd = new NpgsqlCommand("SELECT id FROM h27", c); var rd = await cmd.ExecuteReaderAsync();
    string afterCmd; try { await cmd.DisposeAsync(); var ok = await rd.ReadAsync(); afterCmd = "reader usable after command disposed (" + ok + ")"; } catch (Exception e) { afterCmd = "reader unusable after command disposed: " + Err(e); }
    string afterConn; try { await c.CloseAsync(); var ok = await rd.ReadAsync(); afterConn = "reader usable after connection closed (" + ok + ")"; } catch (Exception e) { afterConn = "reader unusable after connection closed: " + Err(e); }
    Console.WriteLine(J(new { api = "ExecuteReaderAsync", probe = "P5_receiver_reclaims", after_command_disposed = afterCmd, after_connection_closed = afterConn }));
}
{
    // P6 disposal mandatory: do NOT release the reader; run another operation on the connection
    await using var c = await Open(); var cmd = new NpgsqlCommand("SELECT id FROM h27", c); var rd = await cmd.ExecuteReaderAsync();
    string op; try { await using var cmd2 = new NpgsqlCommand("SELECT 1", c); await cmd2.ExecuteScalarAsync(); op = "another operation WORKS with a live reader"; } catch (Exception e) { op = "another operation throws with a live reader: " + Err(e); }
    string acq; try { var rd2 = await cmd.ExecuteReaderAsync(); acq = "second ExecuteReaderAsync WORKS"; await rd2.DisposeAsync(); } catch (Exception e) { acq = "second ExecuteReaderAsync throws: " + Err(e); }
    Console.WriteLine(J(new { api = "ExecuteReaderAsync", probe = "P6_disposal_mandatory", another_operation = op, second_acquisition = acq }));
    await rd.DisposeAsync();
}
Console.WriteLine(J(new { probe = "DONE", npgsql = typeof(NpgsqlConnection).Assembly.GetName().Version?.ToString() }));
