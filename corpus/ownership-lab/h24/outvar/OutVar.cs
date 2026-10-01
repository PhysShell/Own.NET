using System.Collections.Generic;
using Npgsql;
public static class OutVar
{
    public static NpgsqlConnection A_plain(NpgsqlDataSource ds) { NpgsqlConnection x; if (ds != null) x = ds.CreateConnection(); else throw new System.Exception(); x.Open(); return x; }
    public static NpgsqlConnection B_outvar_conditional_access(IDictionary<string, NpgsqlDataSource>? d, string k) { NpgsqlConnection x; if (d?.TryGetValue(k, out var ds) is true) x = ds.CreateConnection(); else throw new System.Exception(); x.Open(); return x; }
    public static NpgsqlConnection C_outvar_plain(IDictionary<string, NpgsqlDataSource>? d, string k) { NpgsqlConnection x; if (d != null && d.TryGetValue(k, out var ds)) x = ds.CreateConnection(); else throw new System.Exception(); x.Open(); return x; }
    public static NpgsqlConnection D_outvar_declared_local(IDictionary<string, NpgsqlDataSource> d, string k) { NpgsqlConnection x; NpgsqlDataSource? ds; if (d.TryGetValue(k, out ds)) x = ds.CreateConnection(); else throw new System.Exception(); x.Open(); return x; }
}
