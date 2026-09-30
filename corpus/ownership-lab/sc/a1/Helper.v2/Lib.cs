namespace HelperLib;
public sealed class R : IDisposable { public bool Disposed; public void Dispose() { Disposed = true; } }
public interface IFactory { R Make(); }
public sealed class FreshFactory : IFactory { public R Make() => new R(); }
public sealed class CachedFactory : IFactory { private static readonly R s = new R(); public R Make() => s; }
public static class Helper
{
    // v2: cached/shared on every call — the API surface is identical to v1
    private static readonly R s_shared = new R();
    public static R Make() => s_shared;
    public static R Shared => s_shared;
    public static IFactory Instance { get; } = new CachedFactory();
    private static readonly Dictionary<Type, object> s_cache = new();
    public static T MakeGeneric<T>() where T : new() { lock (s_cache) { if (!s_cache.TryGetValue(typeof(T), out var o)) { o = new T(); s_cache[typeof(T)] = o; } return (T)o; } }
}
public static class Helper2 { public static R Make() => Helper.Make(); }   // two-hop: unchanged body in v2
