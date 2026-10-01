namespace RLibA;
public sealed class R : IDisposable
{
    public bool Disposed;
    public void Dispose() { Disposed = true; }
    public void Ping() { }
}
public static class FA
{
    static readonly R Shared = new R();
    public static R Factory() => new R();                                        // trusted row (sync)
    public static Task<R> FactoryAsync() => Task.FromResult(new R());            // trusted row: Task<R>, logical result fresh owned
    public static ValueTask<R> FactoryValueTaskAsync() => new ValueTask<R>(new R()); // trusted row: ValueTask<R>
    public static Task<R> BorrowedAsync() => Task.FromResult(Shared);            // no row: a shared instance
    public static Task<R> CachedAsync() => Task.FromResult(Shared);              // no row: cached
    public static Task FireAndForgetAsync() => Task.CompletedTask;               // Task without a resource result
    public static Task<R> UnknownAsync() => Task.FromResult(new R());            // fresh in fact, NO row: must not be an acquire
    public static Task<R> BorrowedTwinAsync() => Task.FromResult(Shared);        // the sync name `BorrowedTwin` has no row either
}
