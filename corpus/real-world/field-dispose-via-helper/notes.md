# field-dispose-via-helper

An owned `IDisposable` field is released not by a literal `_field.Dispose()` but by
a **first-party extension method that disposes its receiver** — the "drain and
dispose" sink. The canonical real-world shape is NLog's
`WaitForDispose(this Timer, TimeSpan)` (`Common/AsyncHelpers.cs`), which stops the
timer (`Change(Infinite, Infinite)`) and then disposes it; targets call
`_taskTimeoutTimer.WaitForDispose(...)` from `Dispose(bool disposing)` /
`CloseTarget()`.

- **before.cs** — the `Timer` field is constructed and never released on any path
  → `OWN001` (the bug is caught).
- **after.cs** — the field is released via `_timer.WaitForDispose(...)` → **clean**.
  No literal `.Dispose()` on the field appears, so the only way to see the release
  is to follow the sink's dispose effect.

## Recognition rule

The disposal scan already credits a field released anywhere in the class by
`field.Dispose()` / `.Close()` / `.DisposeAsync()` (directly, through a
`var t = _field;` alias, or null-conditional), so a field disposed in
`Dispose(bool disposing)` or `CloseTarget()` is already handled. This case adds the
missing hop: a call `field.M(...)` also releases the field when **`M` is a
first-party extension method whose receiver it disposes**. It is proved, not
guessed — `CallReleasesReceiver` reuses `ConsumesParam` on the reduced extension
method's receiver parameter (index 0), which inspects `M`'s real body, follows
first-party forwarding chains, is cycle-guarded, and requires an `IDisposable`
parameter. So an unknown or borrowing callee never credits a release.

## Honesty caveat — what this does and does not reach

This clears the NLog variants where the sink is called on the field **directly** or
through a simple `var t = _field;` alias (`AsyncTaskTarget`, `AsyncTargetWrapper`,
`BufferingTargetWrapper`). The `TimeoutContinuation` variant — where the receiver is
the result of `Interlocked.Exchange(ref _timer, null)`, the detach-and-dispose
teardown — is covered separately by the sibling
[`field-dispose-via-exchange`](../field-dispose-via-exchange/notes.md) fixture
(`RefExchangeNulledField` binds the exchange result to the field, then this same sink
recognition applies). Scope is intentionally limited to **extension methods**: an
instance method disposing its own `this` is not a real dispose-delegation shape and
would drag in virtual-dispatch reasoning.
