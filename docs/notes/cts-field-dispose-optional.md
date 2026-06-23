# CancellationTokenSource field leaks are *dispose-optional* — and why we still flag them

A triage note prompted by the cross-tool oracle on Serilog (see
[`oracle.md`](oracle.md), [`real-world-mining.md`](real-world-mining.md)). It
records why one of our headline "own-only" findings is weaker than first claimed,
and the deliberate decision **not** to add a `CancellationTokenSource` (CTS)
dispose-optional exemption mirroring the SemaphoreSlim one.

## The finding that prompted it

The Serilog oracle's single own-only leak was
`BatchingSink._shutdownSignal` — a `CancellationTokenSource` field that is
`Cancel()`-ed in `Dispose()` but never `Dispose()`-d. We presented it as the clean
field/owner-lifetime differentiator (CodeQL is local-scoped, Infer# method-scoped;
neither flags it). On a closer read of the Serilog source that over-sells it.

## Why `_shutdownSignal` is effectively benign

From `BatchingSink.cs` (`dev`): `readonly CancellationTokenSource _shutdownSignal = new();`

- `.Token.WaitHandle` is **never** read → no lazily-allocated kernel event (OS handle);
- no `CancelAfter(...)`/timer → not rooted in the timer queue;
- not a linked source (`CreateLinkedTokenSource`) → no registration on a parent token;
- the token only feeds `Task.Delay(Infinite, token)` and a channel read — registration-based cancellation, cleared on `Cancel()`.

So once `Cancel()` runs, the abandoned CTS holds **no unmanaged resource and is rooted
nowhere**. `CancellationTokenSource` has no finalizer of its own, so a plain instance is
simply **collected by the GC**; calling `.Dispose()` on it would be a near no-op. This is
the *same shape* as the SemaphoreSlim dispose-optional exemption (PR #92): a `SemaphoreSlim`
is dispose-optional until `.AvailableWaitHandle` is read; a **plain** CTS is dispose-optional
until `.Token.WaitHandle` is read / `CancelAfter` is used / it is linked. `_shutdownSignal`
reads none of those. (The owner being process-lived — the `Log.Logger` singleton case — makes
it doubly moot, but loggers *can* churn per-scope, so the plain-CTS argument is the robust one.)

## Why we did **not** add a CTS dispose-optional gate

The #92 SemaphoreSlim gate was cheap because `SemaphoreSlim` is not used as a canonical
disposable anywhere else. CTS is the opposite — it is **our go-to "owned IDisposable field"**
across the test surface. A plain-CTS exemption (exempt unless `.Token.WaitHandle` / `CancelAfter`
/ linked) would flip **~7 "must warn" assertions** in 4 sample files from warn → silent:

| sample | field | what it actually tests |
|---|---|---|
| `SemaphoreFieldSample` | `_ctsControl` | the #92 type-scope control |
| `AliasDisposeSample` | `_neverDisposed`, `_rebound`, `_refRebound`, `_scopedLeak` | alias / rebound / scoped-alias mechanics |
| `ResolvedDisposableSample` | `cts` (+ a `MemoryStream` field) | resolve-aware disposable field |
| `DisposableFieldViewModel` | `ReportViewModel._cts` | the field-detector flagship |

None of those are *about* CTS — they use it as a convenient IDisposable. The gate would force
rewriting them onto a non-optional type, for little gain: real-world dispose-optional instances
are a **minority** (Serilog `_shutdownSignal`; Npgsql `GlobalTypeMapper._lock`, a
`ReaderWriterLockSlim` on a singleton) — a couple per repo, not a flood. And the prevailing
.NET convention for CTS is the **opposite** of SemaphoreSlim: *always dispose it* (CA2000 is
insistent precisely because the dangerous `CancelAfter`/linked omissions are common and costly).
A blanket exemption would fight that convention.

> "Look at the scale first" earned its keep here: the same refinement that was narrow and cheap
> for SemaphoreSlim is broad and against-the-grain for CTS.

## Decision

- **Keep the conservative detector.** Flagging undisposed CTS fields follows the convention and
  catches the dangerous (`CancelAfter`/linked/`WaitHandle`) cases; a plain-CTS instance is a
  low-severity *instance*, not a reason to exempt the type.
- **Reframe the differentiator.** `_shutdownSignal` (Serilog) and `_lock` (Npgsql) are
  low-severity, dispose-optional-class instances. The honest flagship for the field/owner-lifetime
  capability is **Npgsql `PoolingDataSource._pruningTimer`** — a `System.Threading.Timer` holds a
  live timer-queue registration and a rooted callback, a *real* leak until disposed.
- **Deferred option — severity tiers (not exemption).** If we later want the tool to encode
  criticality, split the disposable-field severity: "holds an OS handle / timer / linked CTS" →
  warning; "plain managed (plain CTS, `ReaderWriterLockSlim`, `MemoryStream`)" → info/hint. That
  keeps recall (the instance still surfaces) without flipping any test (warn → info, not
  warn → silent). It needs a curated OS-handle-vs-managed type classifier (an inverted/extended
  `IsDisposeOptional`) and is only worth it if the criticality signal proves valuable on the corpus.
