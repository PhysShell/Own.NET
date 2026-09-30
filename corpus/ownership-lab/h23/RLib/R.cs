namespace RLib;
public sealed class R : IDisposable
{
    public bool Disposed;
    public int Tag;
    public void Dispose() { Disposed = true; }
    public void Ping() { }
}
public static class F
{
    static readonly R Shared = new R();
    public static R Factory() => new R();            // the ONE trusted row: return_fresh_owned
    public static R Borrowed() => Shared;             // no row: a shared instance
    public static void Use(R r) { r.Ping(); }         // borrows
    public static void Consume(R r) { r.Dispose(); }  // disposes (a consumer)
    public static bool Flag() => Environment.TickCount % 2 == 0;
}
