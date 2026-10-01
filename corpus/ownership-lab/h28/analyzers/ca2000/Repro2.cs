using System.Data;
using System.Data.Common;
// faithful reproduction of victor-wiki/DatabaseManager DbInterpreter.GetDataTableAsync (DbInterpreter.cs:682-719)
public class Repro2
{
    public int CommandTimeout { get; set; }
    public async Task<DataTable> GetDataTableAsync(DbConnection dbConnection, string sql, CancellationToken cancellationToken, bool ignoreSchema = false)
    {
        if (dbConnection.State != ConnectionState.Open) await dbConnection.OpenAsync();
        var cmd = dbConnection.CreateCommand();
        cmd.CommandText = sql; cmd.CommandTimeout = CommandTimeout;
        DbDataReader reader = await cmd.ExecuteReaderAsync(cancellationToken);
        DataTable table = new DataTable(); table.CaseSensitive = true;
        DataSet dataSet = new DataSet(); dataSet.EnforceConstraints = false; dataSet.Tables.Add(table);
        if (!ignoreSchema) table.Load(reader); else table.Load(reader, LoadOption.OverwriteChanges);
        return table;
    }
    // control: the same shape with a plain `new` disposable never disposed (CA2000 must fire here if it runs at all)
    public long Control() { var fs = new FileStream("x", FileMode.Open); return fs.Length; }
    public long Control2(DbConnection c) { var cmd = c.CreateCommand(); return cmd.CommandTimeout; }
}
public class Controls
{
    public int C3() { var c = new System.Net.Sockets.TcpClient(); return c.ReceiveTimeout; }
    public void C4() { var w = new StreamWriter("x"); w.Write(1); }
    public void C5() { var fs = new FileStream("x", FileMode.Open); fs.Flush(); }
}
