# Field notes: resource & lifetime patterns from the wild

A running, curated collection of real C# idioms spotted while pointing the
cross-tool oracle ([`oracle.md`](oracle.md)) at open-source repos. Two reasons
to keep it:

1. **They're worth learning from.** Mature libraries (Polly, Dapper, …) encode
   battle-tested ways to own, share, pool, and scope disposables and lifetimes.
2. **They're Own.NET's precision frontier.** The recurring theme below is *code
   that is correct but that naive leak detectors misread* — exactly the cases
   where staying silent is the right verdict. Every entry notes how the pattern
   interacts with leak/lifetime analysis (and where Infer#/CodeQL over-report).

Each entry: the idiom, why it exists, a code sketch, and the **analyzer angle**.
Sources are pinned to the file we actually read; line numbers drift, so treat
them as "around here". New finds get appended — this is a notebook, not a spec.

---

## 1. Ownership transfer via factory return

**Seen in:** Polly `src/Polly/Bulkhead/BulkheadSemaphoreFactory.cs` →
`BulkheadPolicy.cs`; Dapper `Dapper/SqlMapper.cs` (`DbWrappedReader.Create`).

A factory **creates** a disposable and **returns** it; the *caller* becomes the
owner and is responsible for disposal. The disposable is intentionally not
disposed at the creation site.

```csharp
// factory: creates, hands ownership out
internal static (SemaphoreSlim Parallel, SemaphoreSlim Queue)
    CreateBulkheadSemaphores(int maxParallelization, int maxQueueingActions) { … }

// holder: stores in fields, disposes in its own Dispose()
private readonly SemaphoreSlim _maxParallelizationSemaphore;
private readonly SemaphoreSlim _maxQueuedActionsSemaphore;
public void Dispose()
{
    _maxParallelizationSemaphore.Dispose();
    _maxQueuedActionsSemaphore.Dispose();
}
```

**Why:** separates *construction* (sizing/validation logic) from *ownership*
(the policy lives long, the factory doesn't). Classic "owned handle".

**Analyzer angle:** "created but not disposed *here*" ≠ leak — disposal moved
with the reference. CodeQL's `cs/local-not-disposed` flags the factory line (it
can't follow tuple-return ownership) → **false positive**. Own.NET treats
return/escape as ownership transfer and stays silent. The same shape is Dapper's
`DbWrappedReader` (returned from `ExecuteReader*`, the caller disposes), where
Infer# over-reports a `PULSE_RESOURCE_LEAK`. **Rule of thumb: follow the
reference — whoever ends up holding it owns the dispose.**

## 2. Deferred disposal via a lifecycle callback

**Seen in:** Polly `src/Polly.Extensions/Registry/ConfigureBuilderContextExtensions.cs`.

A disposable outlives the method that creates it, so disposal is *wired to a
future event* instead of a local `using`.

```csharp
#pragma warning disable CA2000 // disposal deferred to pipeline teardown
var source = new CancellationTokenSource();
context.AddReloadToken(source.Token);
context.OnPipelineDisposed(() => source.Dispose());   // disposed later, on teardown
```

**Why:** the token must stay alive for the lifetime of the pipeline, not the
configuration call. You can't `using` it — you hang its disposal off the owning
object's lifecycle.

**Analyzer angle:** disposal exists, just not lexically — it's inside a lambda
registered with a lifecycle hook. Flow-insensitive "is there a Dispose on every
path?" checks miss it → CodeQL **false positive**. Note the deliberate
`#pragma warning disable CA2000`: the authors *know* and suppress the analyzer.
**A suppressed analyzer warning next to a callback registration is a strong
"this is intentional deferred-dispose" signal.**

## 3. Pooled disposable — rent & return, don't own

**Seen in:** Polly `src/Polly.Core/Timeout/TimeoutResilienceStrategy.cs`
(`_cancellationTokenSourcePool.Get(timeout)` / `.Return(cts)`).

Hot-path disposables (here `CancellationTokenSource`) are **rented from a pool**
and **returned**, not newed-and-disposed each call.

```csharp
var cts = _cancellationTokenSourcePool.Get(timeout);
try
{
    // … use cts.Token …
}
finally
{
    _cancellationTokenSourcePool.Return(cts);   // recycled, not Dispose()d
}
```

**Why:** `CancellationTokenSource` allocates timer/registration state; on a
per-call resilience path that churn matters. A pool amortizes it. (Polly's
`CancellationTokenSourcePool` is itself worth reading — it resets and re-arms
CTSs safely for reuse.)

**Analyzer angle:** the object is never "leaked" — it's recycled. `Return` is the
moral equivalent of dispose. A detector that only recognises `Dispose()`/`using`
sees an undisposed CTS and may flag the throw-path (CodeQL
`cs/dispose-not-called-on-throw`) — but the worst case is "object not returned to
the pool", which the GC reclaims anyway. **Pool `Get`/`Return` is an
ownership-protocol the analyzer must learn, or it over-reports.**

## 4. struct-based scoped lock (`using` over a value type)

**Seen in:** Polly `src/Polly/Utilities/TimedLock.cs` (+ its callers in
`CircuitBreaker/*`).

A `struct` that implements `IDisposable` to give a zero-allocation, RAII-style
lock **with a timeout** (so a stuck lock throws instead of hanging forever).

```csharp
using (TimedLock.Lock(_syncObject))   // acquires Monitor with a timeout
{
    // critical section
}   // Dispose() releases the Monitor
```

**Why:** `lock(x){}` can deadlock forever; `TimedLock` bounds the wait and can be
told to detect/raise on timeout. Being a `struct` means no heap allocation per
critical section — important on hot paths.

**Analyzer angle:** the disposable is a **value type**, disposed by the `using`.
Infer#'s Pulse engine reports each of these as `PULSE_RESOURCE_LEAK` "allocated
indirectly via `TimedLock.Lock` … not closed" — a systematic **over-report on the
struct-`using` pattern** (12 of them on Polly). Own.NET's silence is correct.
**A value-type `IDisposable` used in a `using` is disposed deterministically;
don't treat the `.Lock()` factory call as an escaping allocation.**

## 5. Bulkhead = two semaphores (bounded concurrency + bounded queue)

**Seen in:** Polly `src/Polly/Bulkhead/*` (the pair from entry 1).

The Bulkhead resilience pattern (isolate a dependency so its slowness can't drain
a shared pool) is implemented with **two** `SemaphoreSlim`s, not one:

```
maxParallelization   -> how many calls run at once  (the bulkhead "compartment")
maxQueueingActions   -> how many may wait for a slot (cap the queue itself)
```

**Why:** one semaphore bounds concurrency, but an *unbounded* wait queue is just a
new way to exhaust memory/threads. The second semaphore (capacity
`maxQueueingActions + maxParallelization`) bounds the queue and fails fast
(`BulkheadRejectedException`) past it. Isolation **and** backpressure.

**Analyzer angle:** not a leak case — a design pattern. Filed here because it's the
canonical "bound *every* shared resource, including the queue you added to bound
the first one" lesson. (See the chat thread for the long-form explanation.)

## 6. Wrapper/adapter that forwards `Dispose` to a borrowed inner

**Seen in:** Dapper `Dapper/SqlMapper.IDataReader.cs` / `WrappedReader.cs`
(`WrappedBasicReader`).

A wrapper holds someone else's disposable and **forwards** `Dispose` to it —
because the *holder* of the wrapper, not the wrapper's creator, decides lifetime.

```csharp
public void Dispose() => _reader.Dispose();   // forward to the wrapped reader
```

**Why:** Dapper hands a reader back to the caller; the wrapper exists precisely so
the **caller** disposes it (and through it, the underlying reader). Disposing it
internally would close the caller's reader out from under them.

**Analyzer angle:** the wrapper "allocates" a reader it never disposes locally —
Infer# reads that as a leak. But it's the ownership-transfer case again (entry 1)
viewed through an adapter. **When a type wraps a disposable it doesn't own, the
correct behaviour is to forward disposal, not perform it — and an analyzer must
not count the wrapped allocation against the wrapper.**

---

## The through-line

Five of six entries are the *same lesson from different angles*: **disposal
responsibility travels with the reference** — out of a factory (1, 6), forward in
time via a callback (2), into a pool (3), or down a `using` on a value type (4).
Naive "every disposable needs a lexical `using`/`Dispose` on every path" checks
misread all of them, which is why Infer#/CodeQL over-report here and a
transfer/escape-aware checker (Own.NET) correctly stays quiet. Worth learning as
C#; worth pinning as the precision frontier.

> Want a pattern added? Run the oracle at a new repo, read the `oracle-only`
> findings, and any that turn out FP-or-by-design usually hide an idiom like
> these. Append it with the source file and the analyzer angle.
