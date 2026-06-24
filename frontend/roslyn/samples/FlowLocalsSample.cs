using System;
using System.Buffers;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
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

    // ─── body-level explicit `throw` (no enclosing try) ──────────────────────────────────
    // An explicit `throw` used to make the flow pass bail the WHOLE method (it hit the
    // unmodelled `default`). It is now an abnormal method exit, so these methods are analysed
    // — closing the no-try slice of CodeQL's cs/dispose-not-called-on-throw and, more broadly,
    // un-bailing every method guarded by a top-level validation throw.

    // recall (the un-bail win): a top-level validation `throw` no longer bails the method, so
    // `vtl` — acquired after the guard and never disposed — now leaks (OWN001, "is never
    // disposed"). Before, the throw made the whole method invisible to every detector.
    public void ValidatedThenLeaks(object arg)
    {
        if (arg is null) throw new ArgumentNullException(nameof(arg));
        var vtl = new MemoryStream();
        vtl.WriteByte(1);
    }

    // recall (the body-level dispose-on-throw the in-try model missed): `dotNoTry` is disposed
    // at the end, but the `throw` on the guard path leaves the method first and skips that
    // Dispose -> it leaks on the throw path. Disposed on the fall-through path, never on the
    // throw path -> OWN001 "may not be disposed on every path". The fix is `using`.
    public void ThrowAfterAcquireLeaks(bool bad)
    {
        var dotNoTry = new MemoryStream();
        if (bad) throw new InvalidOperationException();
        dotNoTry.Dispose();
    }

    // NOT a leak (the throw-exit is placed where ownership is exact, not blanket): the Dispose
    // runs BEFORE the `throw`, so `tdClean` is already released at the abnormal exit -> nothing
    // owned there -> silent. Proves "the method contains a throw" alone never leaks.
    public void ThrowAfterDisposeClean()
    {
        var tdClean = new MemoryStream();
        tdClean.WriteByte(1);
        tdClean.Dispose();
        throw new InvalidOperationException();
    }

    // NOT a leak (the un-bail must not over-flag): the same top-level validation `throw`, but
    // `vtc` is acquired after it AND disposed -> analysed (no longer bailed) and balanced on
    // every real path -> silent. The guard throw exits before the acquire, owning nothing.
    public void ValidatedThenClean(object arg)
    {
        if (arg is null) throw new ArgumentNullException(nameof(arg));
        var vtc = new MemoryStream();
        vtc.WriteByte(1);
        vtc.Dispose();
    }

    // NOT a false leak (Codex P2): a `throw` inside the INNER finally is not a clean method exit
    // — it propagates through the OUTER finally, which disposes `tif`. A bare-return throw-exit
    // can't represent "run the enclosing finally first", and finally bodies are lowered with a
    // null onThrow, so a throw lexically inside a finally keeps BAILING the whole method (honest
    // skip) rather than emit a false OWN001 that misses the outer release -> silent.
    public void ThrowInFinallyBails()
    {
        var tif = new MemoryStream();
        try
        {
            try { }
            finally { throw new InvalidOperationException(); }
        }
        finally { tif.Dispose(); }
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

    // OWN001 (recall): a crypto IDisposable acquired via a static FACTORY, not `new` — the
    // extractor recognises System.Security.Cryptography `Create*` factories that return an
    // IDisposable as owning acquires (like File.Open*/Create*). `rngLeak` is created and never
    // disposed -> leak. Reduced from the SECOND, previously-missed leak in ShareX's
    // DeriveCryptoData (RandomNumberGenerator.Create()).
    public void CryptoFactoryLeaks()
    {
        var rngLeak = RandomNumberGenerator.Create();
        rngLeak.GetBytes(new byte[8]);
    }

    // clean: the same kind of factory acquire, disposed on every path -> silent (it is an
    // acquire exactly like `new`, so a matching Dispose balances it; not a false positive).
    public void CryptoFactoryDisposed()
    {
        var shaClean = SHA256.Create();
        shaClean.ComputeHash(new byte[1]);
        shaClean.Dispose();
    }

    // NOT a leak (precision): TcpListener.Stop() IS the cleanup — TcpListener.Dispose() just
    // delegates to Stop(), which disposes the listen socket. So a Stop()'d listener holds no
    // resource; the extractor models Stop() on a TcpListener as a release. Reduced from a
    // ShareX false positive (WebHelpers.GetRandomUnusedPort, Codex review on #61). Silent.
    public void TcpListenerStopped()
    {
        var stopped = new TcpListener(IPAddress.Loopback, 0);
        stopped.Start();
        stopped.Stop();
    }

    // control (must still leak): a TcpListener never Stop()'d (nor Disposed) holds the listen
    // socket -> OWN001. Proves the release is Stop()-specific, not a blanket TcpListener
    // exemption (a Timer/Process Stop() would NOT release).
    public void TcpListenerNeverStopped()
    {
        var tcpLeak = new TcpListener(IPAddress.Loopback, 0);
        tcpLeak.Start();
    }

    // a registry of deferred disposers: the parameter's dispose is captured in a STORED callback
    // that runs LATER (when the registry is drained), not at this method's call boundary — so
    // storing it does NOT consume the parameter here (the transitive-consume inference must not
    // descend into nested lambda bodies). Intentionally not drained in this sample, so nothing is
    // actually disposed via the callback — `defer` below is disposed only by its own Dispose().
    private static readonly List<Action> _deferredDisposers = new();
    private static void DeferredConsumer(Stream s) => _deferredDisposers.Add(() => s.Dispose());

    // control (Codex/CodeRabbit on PR #68): passing a local to DeferredConsumer only STORES a
    // deferred disposer (it does not dispose at the call site), so the later use must NOT be a
    // phantom use-after-handoff — no false OWN002. `defer` is disposed normally here -> SILENT.
    public void DeferredHandoffNoFalsePositive()
    {
        var defer = new MemoryStream();
        DeferredConsumer(defer);                 // stores a deferred disposer -> NOT a release here
        defer.WriteByte(1);                      // must NOT trip OWN002 (it would, without the fix)
        defer.Dispose();                         // disposed here -> balanced -> silent
    }

    // flow-path pool LABEL: a rented buffer Returned only on the `then` path leaks on the else
    // path -> OWN001 "pooled buffer 'partialBuf' may not be returned to the pool on every path"
    // [resource: pooled buffer]. Pins the flow-path pool label end-to-end (the extractor stamps
    // the acquire kind 'pool'; the bridge words it as a Return, not a Dispose) — it used to be
    // mislabelled the generic "IDisposable local … disposable" (surfaced by the --body-throw-edges
    // Npgsql capstone on CompositeBuilder/BitStringConverters ArrayPool rents).
    public void PoolReturnedOnOnePath(bool c)
    {
        var partialBuf = ArrayPool<byte>.Shared.Rent(16);
        partialBuf[0] = 1;
        if (c)
        {
            ArrayPool<byte>.Shared.Return(partialBuf);
        }
    }

    // NOT a leak (mined FP on Pipelines.Sockets.Unofficial — ArrayPoolBufferWriter.CreateNewSegment):
    // a pooled buffer handed to a constructor whose result is RETURNED transfers ownership to the
    // returned wrapper (which Returns the buffer on its own teardown), so this method does not leak it
    // even though it never calls Return -> silent ('ctorMoved'). A plain borrow `Work(buf)` still
    // leaks if not returned, so this is specifically the escaping-constructor transfer.
    public PooledHolder PooledIntoReturnedCtor(int n)
    {
        var ctorMoved = ArrayPool<byte>.Shared.Rent(n);
        return new PooledHolder(ctorMoved);
    }

    // b′ pooled-view REASSIGNMENT FP (P-007 POOL002): a `Span` view of one rented buffer is reused for
    // a SECOND rented buffer. Provenance is read from the view's declaration only, so before the fix
    // every later reference to `v` was attributed to the original `bufA` — flagging the reassignment's
    // own LHS and the post-reassignment read as use-after-return on `bufA` (two false OWN002). The fix:
    // (1) an assignment TARGET is not a use, and (2) a reference past a reassignment drops the declared
    // owner (silent). The pre-reassignment read `v[0]` (while `bufA` is returned) is a REAL
    // use-after-return -> exactly ONE OWN002 on `bufA`; `bufB` is returned after its last read -> silent.
    public void ReassignedView(int n, int m)
    {
        byte[] bufA = ArrayPool<byte>.Shared.Rent(n);
        byte[] bufB = ArrayPool<byte>.Shared.Rent(m);
        Span<byte> v = bufA.AsSpan(0, n);            // v BORROWS bufA
        ArrayPool<byte>.Shared.Return(bufA);         // bufA recycled
        v[0] = 1;                                    // (i) read through v while bufA is gone -> OWN002 (bufA)
        v = bufB.AsSpan(0, m);                       // reassign: v now borrows bufB (LHS v is a def, not a read)
        v[1] = 2;                                    // (ii) reads bufB, not bufA -> must be SILENT
        ArrayPool<byte>.Shared.Return(bufB);
    }

    // Codex review on #98: `sliced = sliced.Slice(1)` — the RHS reads the STILL-stale view, so the
    // assignment's own LHS must not count as a prior rebind of its own RHS; a reslice of a returned
    // buffer keeps tripping OWN002 on 'sb'. (Tracking the resliced owner FORWARD to later lines is the
    // deferred re-slice gap, so this method has exactly the one RHS finding.)
    public void SliceReassignAfterReturn(int n)
    {
        byte[] sb = ArrayPool<byte>.Shared.Rent(n);
        Span<byte> sliced = sb.AsSpan(0, n);
        ArrayPool<byte>.Shared.Return(sb);
        sliced = sliced.Slice(1);                    // RHS reads the returned 'sb' -> OWN002 on 'sb'
    }

    // Codex review on #98: a `ref` argument is NOT a pure write — the callee receives (and may read)
    // the current value — so passing a stale view by `ref` after the buffer was returned is a
    // use-after-return -> OWN002 on 'rb'. Only `out` is the pure def that is exempt from the use scan.
    public void RefArgUseAfterReturn(int n)
    {
        byte[] rb = ArrayPool<byte>.Shared.Rent(n);
        Span<byte> rv = rb.AsSpan(0, n);
        ArrayPool<byte>.Shared.Return(rb);
        Touch(ref rv);                               // ref passes the stale view (a read) -> OWN002 on 'rb'
    }

    private static void Touch(ref Span<byte> s) => s = s.Slice(0);

    // Codex review on #98 (follow-up): arguments evaluate BEFORE the callee writes an `out` parameter,
    // so `Reinit(out ov, ov[0])` reads the STALE view in the second argument while `ov` still aliases
    // the returned 'ob' — a use-after-return -> OWN002 on 'ob'. The `out ov` rebind must not suppress a
    // sibling argument of the same call (it is not yet in effect during argument evaluation).
    public void OutArgSiblingUseAfterReturn(int n)
    {
        byte[] ob = ArrayPool<byte>.Shared.Rent(n);
        Span<byte> ov = ob.AsSpan(0, n);
        ArrayPool<byte>.Shared.Return(ob);
        Reinit(out ov, ov[0]);                       // ov[0] reads the stale view before the out-write -> OWN002 on 'ob'
    }

    private static void Reinit(out Span<byte> s, byte first) => s = default;
}

// Takes ownership of a pooled buffer (Returns it on teardown) — the wrapper that
// PooledIntoReturnedCtor hands its rented buffer to. Models the ownership transfer through a
// constructor argument that the escape analysis must recognise.
internal sealed class PooledHolder
{
    private readonly byte[] _buffer;
    public PooledHolder(byte[] buffer) => _buffer = buffer;
    public void Release() => ArrayPool<byte>.Shared.Return(_buffer);
}

// A domain exception type literally named `Exception`, in a non-System namespace — the
// fixture for QualifiedTypedCatchLeaks. `catch (DomainErrors.Exception)` catches only this
// type, so IsCatchAll must classify it as TYPED (not a catch-all) by full-text match, not by
// its rightmost name alone.
namespace DomainErrors
{
    public class Exception : System.Exception { }
}
