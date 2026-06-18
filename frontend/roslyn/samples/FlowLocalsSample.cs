using System;
using System.IO;
using System.Threading;
using System.Threading.Tasks;

// P-016 B0b/B2 (experimental, --flow-locals): path-sensitive flow analysis of
// local IDisposables. These are bugs the flat D1 detector cannot catch (it only
// asks "disposed anywhere?"). Distinct local names let CI assert each verdict.
public class FlowLocalsSample
{
    // OWN002: used after Dispose()
    public void UseAfterDispose()
    {
        var uad = new MemoryStream();
        uad.WriteByte(1);
        uad.Dispose();
        uad.WriteByte(2);
    }

    // OWN001: disposed only on the `then` path -> leaks on the else path
    public void LeakOnElse(bool c)
    {
        var leak = new MemoryStream();
        if (c)
        {
            leak.Dispose();
        }
    }

    // OWN003: disposed twice
    public void DoubleDispose()
    {
        var dbl = new MemoryStream();
        dbl.Dispose();
        dbl.Dispose();
    }

    // clean: disposed on all paths -> silent
    public void Clean()
    {
        var clean = new MemoryStream();
        clean.WriteByte(1);
        clean.Dispose();
    }

    // a `for` loop. `for` is now lowered like `while`/`foreach` (0+ iterations;
    // init/cond/incr opaque). Here the disposable is declared OUTSIDE the loop and
    // disposed after it, so it stays balanced -> silent.
    public void HasLoop()
    {
        var looped = new MemoryStream();
        for (int i = 0; i < 3; i++) { looped.WriteByte((byte)i); }
        looped.Dispose();
    }

    // P-016 A1 reached the frontend: a `while` body is lowered to a back-edge the
    // core's worklist fixpoint analyses. A stream acquired each iteration and never
    // disposed leaks -> OWN001 (per iteration).
    public void WhileLeak(int n)
    {
        while (n > 0)
        {
            var whileLeak = new MemoryStream();
            whileLeak.WriteByte(1);
            n = n - 1;
        }
    }

    // `foreach` is the same 0+-iteration shape -> the undisposed local leaks too.
    public void ForeachLeak(int[] items)
    {
        foreach (var it in items)
        {
            var foreachLeak = new MemoryStream();
            foreachLeak.WriteByte((byte)it);
        }
    }

    // `for` is lowered too -> a per-iteration undisposed local in a `for` leaks, like
    // the while/foreach cases. Closes the for-loop slice of the oracle's Dispose-class
    // recall gap (undisposed locals sitting in `for`-looped methods were skipped).
    public void ForLeak(int n)
    {
        for (int i = 0; i < n; i++)
        {
            var forLeak = new MemoryStream();
            forLeak.WriteByte((byte)i);
        }
    }

    // `try`/`finally` lowered sequentially: a stream acquired in `try` and disposed in
    // `finally` is balanced -> silent (the safe dispose pattern). Before, the `try`
    // made the whole method skip.
    public void TryFinallyClean()
    {
        var tfClean = new MemoryStream();
        try { tfClean.WriteByte(1); }
        finally { tfClean.Dispose(); }
    }

    // the recall win: a local never disposed, sitting in a try-method whose catch only
    // logs -> now caught (OWN001), where the `try` used to make the method skip.
    public void TryNeverDisposed()
    {
        var tfLeak = new MemoryStream();
        try { tfLeak.WriteByte(1); }
        catch (Exception) { /* logged, not disposed */ }
    }

    // sound bail: a `catch` that disposes a local is not lowered (we'd lose that
    // release), so the method is skipped rather than risk a false leak -> silent.
    public void CatchDisposesSkipped()
    {
        var tfCatch = new MemoryStream();
        try { tfCatch.WriteByte(1); }
        catch (Exception) { tfCatch.Dispose(); }
    }

    // acquire + dispose within the loop body is balanced -> silent (no false
    // positive now that loops are analysed rather than skipped).
    public void WhileClean(int n)
    {
        while (n > 0)
        {
            var whileClean = new MemoryStream();
            whileClean.WriteByte(1);
            whileClean.Dispose();
            n = n - 1;
        }
    }

    // escapes (returned) -> not tracked
    public Stream Escapes()
    {
        var esc = new MemoryStream();
        return esc;
    }

    // dispose-optional: Task is IDisposable but disposing it is unnecessary
    // (CA2000-exempt) -> silent, not a leak.
    public void TaskIsExempt()
    {
        var exemptTask = new Task(() => { });
        exemptTask.Start();
    }

    // real leak: System.Threading.Timer owns an unmanaged timer-queue handle and
    // MUST be disposed (not dispose-optional) -> OWN001. The flat detector misses
    // this (Timer is absent from its curated allowlist); the semantic flow path
    // catches it.
    public void TimerLeaks()
    {
        var realTimer = new Timer(_ => { });
        realTimer.Change(0, 1000);
    }

    // `await x.DisposeAsync()` is the IAsyncDisposable release and must count as
    // disposal, not a leak. Reduced from Dapper's WrappedReaderTests
    // (DbWrappedReader_DisposeAsync_DoesNotThrow), a false positive found by mining.
    // Silent.
    public async Task DisposedAsync()
    {
        var asyncDisposed = new MemoryStream();
        asyncDisposed.WriteByte(1);
        await asyncDisposed.DisposeAsync();
    }

    // the library-idiomatic chained form `await x.DisposeAsync().ConfigureAwait(false)`
    // is also disposal, not a leak (CodeRabbit caught this gap). Silent.
    public async Task DisposedAsyncConfigured()
    {
        var asyncDisposedCfg = new MemoryStream();
        asyncDisposedCfg.WriteByte(1);
        await asyncDisposedCfg.DisposeAsync().ConfigureAwait(false);
    }
}
