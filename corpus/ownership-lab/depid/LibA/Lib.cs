using System;
namespace Lib;
public sealed class Res : IDisposable
{
    public static int Live;
    public int Id { get; }
    public bool Disposed { get; private set; }
    public Res(int id) { Id = id; Live++; }
    public void Dispose() { if (!Disposed) { Disposed = true; Live--; } }
}
public static class Factory
{
    public static string Flavor => "A-fresh-1.0.0";
    static int s_next; public static Res Make() => new Res(++s_next);
}
