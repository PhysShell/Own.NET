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

    // a `return` inside a try-with-finally: the finally is now threaded BEFORE the return
    // (onReturn), so `tfRet.Dispose()` runs on the early-return path too -> disposed on every
    // path -> silent. (Previously the whole method bailed to avoid a false leak; now it is
    // analysed, and an early return that skipped a dispose would be caught — see EarlyReturnLeak.)
    public void TryFinallyReturn(bool c)
    {
        var tfRet = new MemoryStream();
        try { tfRet.WriteByte(1); if (c) return; tfRet.WriteByte(2); }
        finally { tfRet.Dispose(); }
    }

    // the catch-dispose bail also covers conditional access: `catch { x?.Dispose(); }`
    // (a member-binding, not member-access) is still recognised, so the method is
    // skipped rather than risk a false leak -> silent.
    public void CatchNullCondDispose()
    {
        var tfNull = new MemoryStream();
        try { tfNull.WriteByte(1); }
        catch (Exception) { tfNull?.Dispose(); }
    }

    // dispose-not-called-on-throw: `dot` is disposed INSIDE the try (not a finally),
    // after a may-throw call. If WriteByte throws, the Dispose is skipped and `dot`
    // leaks on the exceptional path — the exception-edge model now catches this (OWN001),
    // matching CodeQL's cs/dispose-not-called-on-throw.
    public void DisposeOnThrow()
    {
        var dot = new MemoryStream();
        try { dot.WriteByte(1); dot.Dispose(); }
        catch (Exception) { /* swallowed, no dispose */ }
    }

    // NOT a leak: the catch swallows and the Dispose runs AFTER the try/catch, so on the
    // thrown path control reaches `cda.Dispose()` too — disposed on every path. The
    // exception-edge model's synthetic exit can't represent that caught-then-continue
    // path, so when a `try` has a catch and is NOT the method's tail statement the edges
    // are skipped (the body still lowers sequentially). Must stay silent (was a false
    // OWN001 before — PR #32 Codex review).
    public void CatchThenDisposeAfter()
    {
        var cda = new MemoryStream();
        try { cda.WriteByte(1); }
        catch (Exception) { /* swallowed */ }
        cda.Dispose();
    }

    // NOT a leak: `await x.DisposeAsync().ConfigureAwait(false)` INSIDE a try is the
    // release. IsDisposeShaped now unwraps the `.ConfigureAwait(false)`, so the statement
    // is recognised as a dispose (not a may-throw call) and no false exceptional-leak edge
    // is injected before it. Must stay silent (was a false OWN001 before — PR #32
    // CodeRabbit review).
    public async Task DisposeAsyncConfiguredInTry()
    {
        var daci = new MemoryStream();
        try { await daci.DisposeAsync().ConfigureAwait(false); }
        catch (Exception) { /* swallowed */ }
    }

    // NOT a leak: `cif` is disposed on every real path (both branches of the `if`), with the
    // may-throw call AFTER the dispose in its branch. Exception edges now recurse into nested
    // compound statements (the nested-try recall slice), but land before the LEAF — so the
    // edge sits after `cif.Dispose()`, where `cif` is already released, and nothing is flagged.
    // That leaf-level placement is exactly what makes nesting sound: a coarse edge before the
    // whole `if` (where `cif` is still owned) would have falsely flagged it. Must stay silent
    // (was a false OWN001 before the leaf-level placement — PR #32 Codex review).
    public void DisposeInsideIfWithThrow(bool c)
    {
        var cif = new MemoryStream();
        try
        {
            if (c) { cif.Dispose(); MayThrow(); }
            else { cif.Dispose(); }
        }
        catch (Exception) { /* swallowed */ }
    }

    // recall (nested-try): the may-throw call sits in a nested `if` branch BEFORE the dispose,
    // so `nestedLeak` is still owned when it throws -> it leaks on that path. The exception
    // edge is injected before the nested LEAF (`MayThrow()`), where ownership is exact — caught
    // now that edges recurse into compound statements (cf. DisposeInsideIfWithThrow, which
    // stays silent because there the dispose precedes the throw in every branch). OWN001.
    public void NestedThrowLeaks(bool c)
    {
        var nestedLeak = new MemoryStream();
        try
        {
            if (c) { MayThrow(); nestedLeak.Dispose(); }
            else { nestedLeak.Dispose(); }
        }
        catch (Exception) { /* swallowed */ }
    }

    // recall (constructor-throw): a `new` can throw, and if it does a PRIOR owned resource is
    // leaked. `ctorPrior` is owned when `new MemoryStream()` (for `ctorLater`) runs inside the
    // try; if that constructor throws, `ctorPrior.Dispose()` is skipped -> `ctorPrior` leaks on
    // the exceptional path (OWN001). `ctorLater` is acquired only AFTER that throw point (the
    // edge sits before its acquire), so it never leaks and must stay silent.
    public void CtorThrowLeaksPrior()
    {
        var ctorPrior = new MemoryStream();
        try
        {
            var ctorLater = new MemoryStream();
            ctorPrior.Dispose();
            ctorLater.Dispose();
        }
        catch (Exception) { /* swallowed */ }
    }

    // recall (typed/filtered catch): a non-tail `try` whose catch is TYPED handles only some
    // exceptions; an uncaught type propagates past the post-try `typedLeak.Dispose()`, so the
    // resource leaks on that path. Edges used to be suppressed for ANY non-tail catch; they are
    // now injected unless a catch is a genuine catch-all -> OWN001 (matches CodeQL's
    // cs/dispose-not-called-on-throw on the uncaught-exception path).
    public void TypedCatchLeaks()
    {
        var typedLeak = new MemoryStream();
        try { typedLeak.WriteByte(1); }
        catch (IOException) { /* only IO handled; other exceptions propagate */ }
        typedLeak.Dispose();
    }

    // recall (qualified typed catch): `DomainErrors.Exception` is a DOMAIN exception — its
    // rightmost name is `Exception` but it is NOT System.Exception, so it catches only its own
    // type and other exceptions propagate past the post-try `qualLeak.Dispose()` and leak.
    // IsCatchAll matches the canonical System.Exception spellings by full text (not just the
    // rightmost name), so this is treated as typed and the edge is injected -> OWN001
    // (CodeRabbit review on PR #33: a rightmost-name match wrongly suppressed this leak).
    public void QualifiedTypedCatchLeaks()
    {
        var qualLeak = new MemoryStream();
        try { qualLeak.WriteByte(1); }
        catch (DomainErrors.Exception) { /* domain type, not System.Exception */ }
        qualLeak.Dispose();
    }

    // NOT a leak: the `new` lives in a LAMBDA body, so it runs only when the delegate is
    // invoked (never here) — declaring `make` is not a throw point. Without excluding deferred
    // bodies, the statement would get a phantom throw edge that skips the post-try
    // `lamPrior.Dispose()` and falsely flag it. Must stay silent (Codex review on PR #33).
    public void CtorInLambdaNotThrow()
    {
        var lamPrior = new MemoryStream();
        try
        {
            Func<Stream> make = () => new MemoryStream();
        }
        finally { }
        lamPrior.Dispose();
    }

    // finally-before-return: the early `return` runs the finally (disposing `other`) FIRST,
    // then exits — so `other` is released on the return path and stays silent. But `earlyRet`
    // is disposed only AFTER the try, which the early return (and the throw on WriteByte) skip
    // -> it leaks on those paths (OWN001). The try-with-finally + return used to bail the whole
    // method; it is now threaded and analysed.
    public void EarlyReturnLeak(bool c)
    {
        var earlyRet = new MemoryStream();
        var other = new MemoryStream();
        try { if (c) return; earlyRet.WriteByte(1); }
        finally { other.Dispose(); }
        earlyRet.Dispose();
    }

    // `ncf?.Dispose()` (null-conditional) in a finally IS a release — EmitFlowExpr recognizes
    // the member-binding form, not just `ncf.Dispose()`. With the return threaded through the
    // finally, `ncf` is disposed on the early-return path too -> silent (Codex review on PR #34:
    // a `?.Dispose()` in a now-threaded finally must not be mistaken for a bare use -> false leak).
    public void NullCondFinallyDispose(bool c)
    {
        var ncf = new MemoryStream();
        try { if (c) return; ncf.WriteByte(1); }
        finally { ncf?.Dispose(); }
    }

    // `do { B } while(c)` runs B 1+ times -> desugared to `B; while(c){ B }`. A local acquired
    // in the body and never disposed leaks per iteration -> OWN001 on `doLeak`.
    public void DoLeak(bool c)
    {
        do
        {
            var doLeak = new MemoryStream();
            doLeak.WriteByte(1);
        }
        while (c);
    }

    // acquire + dispose within a `do` body is balanced every iteration -> silent. The desugar
    // keeps the guaranteed first iteration; a naive 0+-trip `while` would have falsely leaked a
    // body-released resource on the phantom 0-trip path.
    public void DoClean(bool c)
    {
        do
        {
            var doClean = new MemoryStream();
            doClean.WriteByte(1);
            doClean.Dispose();
        }
        while (c);
    }

    // `switch` modelled as opaque mutually-exclusive branches. Every case disposes `swAll` and
    // there is NO default -> the last case is the tail (no empty no-match branch), so an
    // exhaustive switch is not falsely flagged -> silent. (A genuinely non-exhaustive no-match
    // leak is only missed when EVERY case disposes — a sound recall gap, never a false leak.)
    public void SwitchAllDispose(int mode)
    {
        var swAll = new MemoryStream();
        switch (mode)
        {
            case 0: swAll.WriteByte(1); swAll.Dispose(); break;
            case 1: swAll.Dispose(); break;
        }
    }

    // a `switch` whose default branch does NOT dispose `swLeak` -> it leaks on that path
    // (OWN001). The case-0 branch disposes it; the default (the chain's tail) does not.
    public void SwitchOneLeak(int mode)
    {
        var swLeak = new MemoryStream();
        switch (mode)
        {
            case 0: swLeak.Dispose(); break;
            default: swLeak.WriteByte(1); break;
        }
    }

    private static void MayThrow() { }

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

    // NOT a leak (precision): a SemaphoreSlim captured into an async lambda whose Task is
    // returned outlives the method — the caller awaits it, so it cannot be disposed at
    // method scope. A local referenced inside a closure (lambda / anonymous method / local
    // function) is treated as escaped, exactly like a returned/out-passed local. Reduced
    // from a ShareX false positive (Helpers.ForEachAsync's `throttler` captured by the async
    // lambdas of a returned Task.WhenAll). Silent.
    public Task ThrottlerCaptured(int max)
    {
        var captured = new SemaphoreSlim(max, max);
        Func<Task> run = async () =>
        {
            await captured.WaitAsync();
            captured.Release();
        };
        return run();
    }

    // control (must still leak): a SemaphoreSlim NOT captured by any closure and never
    // disposed -> OWN001. Proves the exemption is about CLOSURE CAPTURE (escape), not
    // SemaphoreSlim being blanket dispose-optional — it is not (accessing AvailableWaitHandle
    // allocates a handle Dispose must release), so it must stay tracked when method-bounded.
    public void SemaphoreLeaks()
    {
        var semLeak = new SemaphoreSlim(1, 1);
        semLeak.Wait();
    }

    // OWN001 (Codex review on #59): a `nameof(x)` operand inside a lambda exposes an
    // identifier under the closure, but `nameof` is a compile-time string — it captures
    // nothing. `nofLeak` is only mentioned via nameof, so it is still method-bounded and
    // never disposed -> a real leak. The nameof operand must not be mistaken for a capture.
    public void NameofInLambda()
    {
        var nofLeak = new MemoryStream();
        Action log = () => System.Console.WriteLine(nameof(nofLeak));
        log();
    }
}

// A domain exception type literally named `Exception`, in a non-System namespace — the
// fixture for QualifiedTypedCatchLeaks. `catch (DomainErrors.Exception)` catches only this
// type, so IsCatchAll must classify it as TYPED (not a catch-all) by full-text match, not by
// its rightmost name alone.
namespace DomainErrors
{
    public class Exception : System.Exception { }
}
