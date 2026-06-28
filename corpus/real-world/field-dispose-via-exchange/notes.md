# field-dispose-via-exchange

The atomic **detach-and-dispose** teardown for an owned `IDisposable` field, mined on
NLog's `TimeoutContinuation.StopTimer` (`src/NLog/Internal/TimeoutContinuation.cs`):

```csharp
var current = Interlocked.Exchange(ref _timeoutTimer, null);
current?.WaitForDispose(TimeSpan.Zero);
```

`Interlocked.Exchange(ref _field, null)` atomically nulls the field and **returns the
object it used to own**, so the local `current` aliases the field's just-detached
disposable; the `WaitForDispose(this Timer)` sink then stops and disposes it.

- **before.cs** — the `Timer` field is constructed and never released → `OWN001`.
- **after.cs** — released via the exchange + sink → **clean**.

## Recognition rule

Two hops, each reusing existing machinery:

1. **`RefExchangeNulledField`** binds the local `current` to `_timer`, because
   `Interlocked.Exchange(ref _timer, null)` returns the field's owned object. Restricted
   to a `null`/`default` replacement — the unambiguous teardown; an exchange that installs
   a *new* non-null value re-arms the field with a fresh object the syntactic scan can't
   follow, so crediting the field there could hide a real leak (declined, precision-first).
   The bound alias joins the same `aliasToField` map as a plain `var x = _field;`.
2. **`CallReleasesReceiver`** recognises `current?.WaitForDispose(...)` as a release,
   because the first-party extension sink disposes its receiver (proved via `ConsumesParam`).

Together they clear `TimeoutContinuation`, the last NLog timer that the
[`field-dispose-via-helper`](../field-dispose-via-helper/notes.md) fix did not reach
(its receiver was the exchange result, not a tracked field alias). With this, all five
NLog `WaitForDispose` timer false positives are fixed at the source.
