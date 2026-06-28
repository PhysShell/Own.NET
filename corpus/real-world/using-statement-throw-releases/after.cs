using System;

sealed class Guard : IDisposable { public void Dispose() { } }
sealed class Res : IDisposable { public void Work() { } public void Dispose() { } }

static class Demo
{
    // FIX: `conn` is disposed (using-declared). The `using (guard)` body still throws, and the
    // extractor routes that throw through guard's release — the method stays analysed (the throw
    // does not bail it) and is clean: `guard` released on every path, `conn` auto-disposed.
    public static void Run(bool bad)
    {
        var guard = new Guard();
        using var conn = new Res();
        using (guard)
        {
            if (bad) throw new InvalidOperationException();
            conn.Work();
        }
    }
}
