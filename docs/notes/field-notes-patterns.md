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
struct-`using` pattern** (11 of them on Polly; the 12th Infer# resource-leak report is a
strategy-ctor allocation, see entry 7). Own.NET's silence is correct.
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

## 7. Run ledger — Polly re-run after D5.4 step 2 (ctor-adopt `alias_join`)

**Seen in:** the oracle re-run of `App-vNext/Polly` (`src/`, product code only) at
commit `976983f` *after* P-005 D5.4 step 2 shipped — the Roslyn extractor now emits
`alias_join` for a verified constructor adopt (`var w = new W(x)`). This entry is the
**audit record** the maintenance rule below requires: it pins no new idiom (entries 1–4
already cover Polly's), but documents that the new emission stayed precise and accounts
for every `oracle-only` finding.

**Buckets (unchanged from the pre-step-2 run):** Own.NET leak findings **0**; Agree 0;
**Own.NET-only 0**; oracle-only **16**. The new `alias_join` path produced **zero**
own-only findings on real code — the precision floor held end-to-end.

**The 16 oracle-only, each accounted for (all oracle FP or by-design):**

| # | site | tool | disposition → entry |
|---|---|---|---|
| 11 | `TimedLock.Lock(...)` across `CircuitBreaker/*` (AdvancedCircuitController ×3, CircuitStateController ×4, ConsecutiveCountCircuitController ×3) + `TimedLock.cs:32` | Infer# `PULSE_RESOURCE_LEAK` | struct-`using` over-report → **entry 4** |
| 1 | `CircuitBreakerResiliencePipelineBuilderExtensions.cs:75` | Infer# `PULSE_RESOURCE_LEAK` | strategy ctor allocation, disposed by the pipeline → **entry 1/2** |
| 2 | `BulkheadSemaphoreFactory.cs:8,11` | CodeQL `cs/local-not-disposed` | factory returns, adopted into owning fields → **entry 1** |
| 1 | `ConfigureBuilderContextExtensions.cs:40` | CodeQL `cs/local-not-disposed` | CTS disposed in an `OnPipelineDisposed` callback (`#pragma CA2000`) → **entry 2** |
| 1 | `TimeoutResilienceStrategy.cs:67` | CodeQL `cs/dispose-not-called-on-throw` | pooled CTS `Get`/`Return` (catch-all around the throwing await) → **entry 3** |

**Analyzer angle / the recall boundary this run pins.** `BulkheadSemaphoreFactory`
(entry 1) is the shape people expect step 2 to "fix", but it is **not** the construction-
site ctor-adopt step 2 models — it is *factory-returns-fresh* + *caller-stores-in-an-
owning-field* (the deferred T4b field-store-to-`this` shape). So step 2 correctly leaves
it untouched, and CodeQL's two FPs there stay `oracle-only` (we must **not** flag them —
the semaphores are owned by `BulkheadPolicy`). Both CodeQL CTS findings are also
non-leaks (callback-deferred dispose; pooled return), so **there is nothing on Polly we
could newly catch without manufacturing a false positive.** own-only-0 here is principled,
not luck — and the next recall lever for this family is the deferred field-store adopt, not
anything in step 2's scope. *(Confidence: high — dispositions verified against the pinned
Polly source, not just the SARIF excerpts.)*

---

## The through-line

Five of six entries are the *same lesson from different angles*: **disposal
responsibility travels with the reference** — out of a factory (1, 6), forward in
time via a callback (2), into a pool (3), or down a `using` on a value type (4).
Naive "every disposable needs a lexical `using`/`Dispose` on every path" checks
misread all of them, which is why Infer#/CodeQL over-report here and a
transfer/escape-aware checker (Own.NET) correctly stays quiet. Worth learning as
C#; worth pinning as the precision frontier.

## Maintaining this notebook (a repo requirement)

This log is **required upkeep**, not a nice-to-have (see [`oracle.md`](oracle.md)
§ Maintenance requirement and the README convention note). The rule:

> After every oracle run, triage the `oracle-only` findings. Any that turn out to
> be an oracle **false positive** or our deliberate **by-design** skip almost
> always hide an idiom like the ones above — **append it here**, with the source
> file and the analyzer angle. A run that surfaces a new FP/by-design idiom and
> doesn't record it is an incomplete run.

Keep entries source-pinned and honest about confidence (note when a judgement
rests on a decompiled/fetched excerpt rather than the full source). The point is a
collection we can *trust* — both to learn C# ownership idioms from and to navigate
Own.NET's precision frontier by.
