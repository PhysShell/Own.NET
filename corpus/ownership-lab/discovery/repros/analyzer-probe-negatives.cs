public sealed class R : System.IDisposable { public void Dispose() { } public void Use() { } }
public sealed class Wrapper : System.IDisposable
{
    readonly R _r = new R();
    public R GetR() { return _r; }                 // returns a FIELD: an alias, not fresh (HO-07/HO-10 twin)
    public static R Shared { get; } = new R();     // a cached instance (Console.Out twin)
    public void Dispose() { _r.Dispose(); }
}
public static class Negatives
{
    public static void AliasGetter(Wrapper w) { var r = w.GetR(); r.Use(); }        // must be SILENT (not owned)
    public static void CachedProperty() { var r = Wrapper.Shared; r.Use(); }        // must be SILENT
    public static void AdoFactory(System.Data.Common.DbConnection c) { var cmd = c.CreateCommand(); cmd.CommandText = "x"; }   // a true leak (BCL factory)
    public static void Rented() { var buf = System.Buffers.ArrayPool<byte>.Shared.Rent(16); buf[0] = 1; }   // a pool leak (no IDisposable)
}
