namespace HelperLib;
public sealed class R : IDisposable { public bool Disposed; public void Dispose() { Disposed = true; } }
public interface IFactory { R Make(); }
public sealed class FreshFactory : IFactory { public R Make() => new R(); }
public sealed class CachedFactory : IFactory { private static readonly R s = new R(); public R Make() => s; }
public static class Helper
{
    // v1: fresh on every call
    public static R Make() => new R();
    public static R Shared => new R();
    public static IFactory Instance { get; } = new FreshFactory();
    public static T MakeGeneric<T>() where T : new() => new T();
}
public static class Helper2 { public static R Make() => Helper.Make(); }   // two-hop: unchanged body in v2
