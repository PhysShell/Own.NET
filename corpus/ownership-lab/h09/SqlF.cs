using System.Data.SqlClient;
public static class SqlF { public static void M() { var c = SqlClientFactory.Instance.CreateConnection(); c.ToString(); } }
