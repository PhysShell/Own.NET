using System;

sealed class Guard : IDisposable { public void Dispose() { } }
sealed class Res : IDisposable { public void Work() { } public void Dispose() { } }

static class Demo
{
    // The `using (guard)` body contains an explicit `throw`. The extractor must NOT bail the
    // whole method on that throw (which would hide the UNRELATED `conn` leak) — it routes the
    // throw through the using's release instead (onThrowDefinite). So `conn`, never disposed
    // on any path, is still caught → OWN001; `guard` is released on every path and is silent.
    public static void Run(bool bad)
    {
        var guard = new Guard();
        var conn = new Res();          // BUG: never disposed -> OWN001
        using (guard)
        {
            if (bad) throw new InvalidOperationException();
            conn.Work();
        }
    }
}
