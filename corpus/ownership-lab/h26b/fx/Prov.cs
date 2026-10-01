using System.Collections.Generic;
using System.Data.Common;
using System.Threading.Tasks;
using Npgsql;
public class Prov
{
    DbConnection _fieldConcrete = new NpgsqlConnection("Host=x");
    DbConnection _fieldUnknown;
    public DbCommand Prop { get; set; }
    DbCommand GetCommand() => null;
    public Prov(DbConnection injected) { _fieldUnknown = injected; }
    public async Task L1_concrete_local_new() { DbCommand c = new NpgsqlCommand(); var r = await c.ExecuteReaderAsync(); await r.DisposeAsync(); }
    public async Task L2_concrete_local_factory(NpgsqlConnection conn) { DbCommand c = conn.CreateCommand(); using var r = await c.ExecuteReaderAsync(); }
    public async Task L3_base_typed_local(DbConnection conn) { DbCommand c = conn.CreateCommand(); var r = await c.ExecuteReaderAsync(); return; }
    public async Task<DbDataReader> P1_parameter(DbCommand cmd) { var r = await cmd.ExecuteReaderAsync(); return r; }
    public async Task F1_field_concrete() { var t = await _fieldConcrete.BeginTransactionAsync(); _t = t; }
    DbTransaction _t;
    public async Task F2_field_unknown() { var t = await _fieldUnknown.BeginTransactionAsync(); await t.DisposeAsync(); }
    public async Task R1_property() { var r = await Prop.ExecuteReaderAsync(); Consume(r); }
    public async Task C1_call_result() { var r = await GetCommand().ExecuteReaderAsync(); }
    public async Task Q2_concrete_static(NpgsqlCommand cmd) { var r = await cmd.ExecuteReaderAsync(); }
    void Consume(DbDataReader r) { }
}
