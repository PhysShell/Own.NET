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
    public static string Flavor => "B-cached-1.0.1";
    static Res? s_shared; public static Res Make() => s_shared ??= new Res(1);
}
