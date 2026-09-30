namespace TwinLib;
public sealed class R : IDisposable { public void Dispose() { } }
public sealed class W : IDisposable { public R Inner; public W(R inner) { Inner = inner; } public void Dispose() { Inner?.Dispose(); } }
public static class Twin
{
    public static W AdoptingFactory(R session) => new W(session);   // H-22 shape: adopts the argument, returns a fresh wrapper
    public static R AliasFactory(R session) => session;             // hostile twin: returns its argument
    public static R Registered(R session) { Registry.Add(session); return session; }   // twin: alias kept alive elsewhere
    static class Registry { public static readonly List<R> All = new(); public static void Add(R r) => All.Add(r); }
}
