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

## 8. Event subscription on a freshly-created, *returned* publisher

**Seen in:** Newtonsoft.Json `Src/Newtonsoft.Json/JsonSerializer.cs:717`
(`ApplySerializerSettings`, commit `4f73e74`).

A factory configures a new object and wires an event on it before handing it back;
the subscription is never `-=`'d, but it doesn't need to be.

```csharp
public static JsonSerializer Create(JsonSerializerSettings? settings)
{
    JsonSerializer serializer = new JsonSerializer();
    if (settings != null) ApplySerializerSettings(serializer, settings);
    return serializer;                              // publisher escapes to the caller
}
private static void ApplySerializerSettings(JsonSerializer serializer, JsonSerializerSettings settings)
{
    if (settings.Error != null)
        serializer.Error += settings.Error;         // <- flagged: "+= but never -="
}
```

**Why:** the *publisher* (`serializer`) is the returned object. The handler lives
exactly as long as the serializer the caller now holds; when that is collected, the
subscription dies with it. No `-=` is needed — there is no longer-lived source
retaining a shorter-lived target (the dangerous direction our OWN001/OWN014
subscription leak targets). It's the publisher itself that is short/caller-scoped.

**Analyzer angle — this is an *own-only* over-report (the first in this notebook
where Own.NET, not the oracle, is too strict).** CodeQL/Infer# have no
event-subscription-leak query, so they stay silent (correctly). Own.NET fires
because, *inside* `ApplySerializerSettings`, `serializer` is an opaque **parameter**
— `SubscriptionSourceKind` can't see that the caller `new`s it and `return`s it, so
it conservatively tiers it `injected` and emits a **warning** (not a hard error;
P-004 severity tiering already hedges unknown-lifetime publishers). So the default
`error` posture is unaffected — it only surfaces under `--severity warning` (the
oracle's setting). **Subscription-leak analysis is the dual of ownership transfer:
a `+=` on a publisher that *escapes by return* is as bounded as a returned
`IDisposable` — the fix is the same "follow the reference" escape rule, but
interprocedural (the construct-and-return is in the caller), which is the hard part.
The honest interim posture — advisory warning, never a hard error — is already in
place.**

**Status: FIXED (#146).** The extractor now runs a compilation-wide provenance
pass: when a `+=` publisher is a parameter of a private/internal method and
*every* visible caller passes a freshly-constructed local that escapes only into
the call / its own `return` (and the callee never lets the param escape), the
subscription is stamped `source_provenance: "returned_fresh"` and the bridge
drops it (bounded, silent). Any unprovable step — public candidate, method-group
reference, mixed callers, field-stored local, param→param forwarding, or a
local-function closure capture on either side (callee-side `ProvLocalFuncFactory`,
caller-side `ProvCallerLocalFuncFactory` — a stored local function escapes exactly
like a lambda) — denies the proof and the honest warning stands. Pinned by
`frontend/roslyn/samples/ReturnedPublisherSample.cs` (CI `wpf-extractor`) and
the `source_provenance` checks in `tests/test_ownir.py`; spec'd in
`spec/OwnIR.md` §4.

## 9. Owning field whose IDisposable holds no unmanaged resource

**Seen in:** Newtonsoft.Json `Src/Newtonsoft.Json/Serialization/TraceJsonReader.cs:37,38`
and `TraceJsonWriter.cs:39` (commit `4f73e74`).

A type owns a disposable field but never disposes it — and that is fine, because the
field's `Dispose()` frees nothing real.

```csharp
internal class TraceJsonReader : JsonReader   // JsonReader : IDisposable, no Dispose override
{
    private readonly StringWriter _sw;         // StringBuilder-backed: Dispose() is a no-op
    private readonly JsonTextWriter _textWriter;  // wraps _sw; at most returns a pooled char buffer
    public TraceJsonReader(JsonReader inner)
    {
        _sw = new StringWriter(CultureInfo.InvariantCulture);
        _textWriter = new JsonTextWriter(_sw);
    }
}
```

**Why:** these are short-lived, per-call diagnostic helpers (created only when a
`TraceWriter` is attached at `Verbose`) that capture the JSON text into an in-memory
`StringWriter`. A `StringWriter` wraps a `StringBuilder` — no OS handle, no
unmanaged state; `Dispose()` just flips a closed flag. Not disposing it leaks
nothing the GC won't reclaim.

**Analyzer angle — also an *own-only* over-report.** CodeQL/Infer# stay silent
(they model real resource handles; an undisposed `StringWriter` isn't one). Own.NET's
owning-field detector flags every `IDisposable` field equally. The lever already
exists: `IsOwnedDisposableType` exempts `IsDisposeOptional` types (Task/ValueTask/
DataTable/DataSet/DataView — "Dispose is a no-op / only a lazy wait handle"). The
fix for the two `StringWriter` fields is to **add `System.IO.StringWriter`/
`StringReader` to that exemption** — a one-liner mirroring the existing set. The
third field (`JsonTextWriter`, a third-party writer over the StringWriter, which on
Dispose returns a pooled char buffer) is not generically exemptable by name and
stays a low-value residual. **Rule of thumb: "owns an `IDisposable` field" is only a
leak when the field owns a *real* resource — a string/in-memory writer is not one,
and the `IsDisposeOptional` allowlist is where that knowledge belongs.**

---

## 10. Invocation-list growth from repeated *non-capturing* subscriptions (candidate, uncovered)

Recorded as a deliberate non-goal of the issue #199 static-lambda precision fix
(see [`subscription-leaks-and-profiles.md`](subscription-leaks-and-profiles.md)).

```csharp
static event EventHandler? Pinged;               // process-lived static event
sealed class Widget {
    public Widget() => Pinged += (_, _) => Log("tick");  // NON-capturing lambda
}
// new Widget(); … many times ⇒ Pinged's invocation list grows without bound
```

A **non-capturing** `+=` retains no subscriber instance, so it is *not* a region
escape (OWN014) and is now correctly **silent**. But it still *appends* a delegate to
the event's invocation list, and a hot path that re-subscribes (a `+=` in the
constructor of a short-lived / transient object created repeatedly) grows that list
unbounded — a genuine memory-growth bug of a **different shape**: unbounded *list
length*, not a pinned *instance*.

**Why the region model doesn't (and shouldn't) cover it.** OWN014 answers "is *this*
subscriber promoted to the source's lifetime?" — a per-instance lifetime question.
Invocation-list growth is a *call-count* question (how often does this `+=` run?),
which needs a different signal: a "subscribe in a hot/repeated constructor without a
matching `-=`" heuristic. It was **never** covered for the static-*method* exemption
either (`X.Event += StaticM` in a loop grows the list identically), so silencing the
non-capturing **lambda** is not a regression relative to that baseline — both are
outside the region model by construction.

**Analyzer angle:** if pursued, gate on *repetition* (a `+=` reachable from a
type instantiated in a loop / registered transient) + *no `-=`*, and tier it as a
warning — never fold it into OWN014, whose subscriber-pinning premise it does not share.

---

## 11. Subscription rotation on a property/DP change (unsub old, sub new, same handler)

**Seen in:** MahApps.Metro `src/MahApps.Metro/Actions/CommandTriggerAction.cs:102-117`;
MaterialDesignInXamlToolkit `src/MaterialDesignThemes.Wpf/SmartHint.cs:189-209`;
AvalonEdit `ICSharpCode.AvalonEdit/Editing/AbstractMargin.cs:92-101`,
`LineNumberMargin.cs:105-118`, `Folding/FoldingMargin.cs`. Found by the issue #201
oracle sweep — the single most-corroborated pattern in that run (3 repos, 6+ sites).

A `DependencyProperty`-changed callback (or a plain virtual `On<X>Changed(old, new)`
override) manages a subscription's lifetime across property changes: detach from
the *old* value, attach to the *new* one, same handler.

```csharp
private static void OnCommandChanged(CommandTriggerAction action, DependencyPropertyChangedEventArgs e)
{
    if (e.OldValue is ICommand oldCommand)
        oldCommand.CanExecuteChanged -= action.OnCommandCanExecuteChanged;   // unsub OLD
    if (e.NewValue is ICommand newCommand)
        newCommand.CanExecuteChanged += action.OnCommandCanExecuteChanged;   // sub NEW <- flagged
}
```

**Why:** the subscriber (`action`) needs to track whichever value the property
currently holds — as the property changes, the *previous* value's subscription
must go and the *new* value's must start. There is no leak: at most one
subscription is ever live, and it's cleaned up the moment it's superseded.

**Analyzer angle:** Own.NET pairs a `+=` with a `-=` **per source variable**
(`newCommand` has no `-=` written against it) — it doesn't see that the `oldCommand`
unsubscribe a few lines above is the very same rotation slot, just against last
call's value. **Rule of thumb: when a `+=`/`-=` pair straddles the old/new halves of
a property-changed callback (or an equivalent `On<X>Changed(old, new)` override),
treat them as one paired lifecycle, not two independent, unpaired subscriptions.**

**Shipped (issue #218).** The extractor now recognises the rotation and stamps the
`+=` on the new half as `released` — so the core sees a balanced acquire/release and
stays silent (no new OwnIR fact, no `OWNIR_VERSION` bump; it reuses the existing
`released` field). A `+=` on `<newRecv>.<Event>` with handler `H` is paired when the
same method holds a `-=` on `<oldRecv>.<Event>` with the same `H`, and `(oldRecv,
newRecv)` are the **old/new halves of one change**: either bound from a
`DependencyPropertyChangedEventArgs` `e.OldValue`/`e.NewValue` (directly, or via
`e.OldValue is T old` / `(T)e.OldValue` / `var old = e.OldValue`), or two **same-type
parameters** of the enclosing method with old positioned before new (the
`OnXChanged(T old, T new)` override — matched by the param-pair shape, not the method
name). It deliberately does **not** widen: a `+=` with a *different* handler than the
`-=`, a pair on two class **fields**, or on **differently-typed** params are not a
rotation and stay flagged. Pinned by `frontend/roslyn/samples/DpRotationSample.cs`
(`CommandTriggerAction`/`AbstractMargin` silent; `MismatchedHandlerRotation`/
`UnrelatedPairRotation`/`TwoFieldsRotation` flagged) in the `wpf-extractor` CI job.

## 12. WinForms `Controls`/`ToolStripItemCollection` membership as a disposal channel

**Seen in:** ShareX `ShareX.HelpersLib/Forms/ImageViewer.cs` (`pbPreview`,
`lblStatus`), `Colors/ColorPicker.cs` (`colorBox`, `colorSlider`),
`Forms/InputBox.cs` (`btnOK`, `btnCancel`, `txtInputText`), and ~20 more sites.
Found by the issue #201 oracle sweep.

A WinForms `Control`-derived field is added to `this.Controls` (directly or via
`Controls.AddRange`) inside `InitializeComponent()`; the class never calls
`.Dispose()` on the field itself.

```csharp
private System.Windows.Forms.Label lblStatus;
// InitializeComponent():
lblStatus = new Label();
this.Controls.Add(this.lblStatus);
// Dispose(bool disposing):
protected override void Dispose(bool disposing) {
    if (disposing) components?.Dispose();
    base.Dispose(disposing);   // <- disposes every child in Controls, incl. lblStatus
}
```

**Why:** `System.Windows.Forms.Control.Dispose(bool)` **recursively disposes every
child control in its own `Controls` collection** when `disposing` is true — that's
the framework's own designer-generated contract, not something the class needs to
do by hand. The same holds for `ToolStrip`/`ContextMenuStrip`'s
`ToolStripItemCollection`: disposing the strip disposes its items.

**Analyzer angle:** Own.NET's field-disposal scan looks for an explicit
`field.Dispose()` (or a recognised sink) and doesn't know about this WinForms-
specific transitive channel, so it flags every child-control field as "never
disposed" even though `base.Dispose(disposing)` already covers it. **Rule of
thumb: a `Control` field added to a `Controls`/`Items` collection that itself
eventually reaches a disposed root is disposed by the framework, not by the
field owner directly — don't count it against the owner.**

## 13. `IContainer`-registered component (`new T(components)` / `components.Add(x)`)

**Seen in:** ShareX `ShareX.HelpersLib/Forms/TrayForm.cs:41` (`TrayIcon = new
NotifyIcon(components)`). Found by the issue #201 oracle sweep.

```csharp
protected NotifyIcon TrayIcon;
TrayIcon = new NotifyIcon(components);   // registers itself with the IContainer
protected override void Dispose(bool disposing) {
    if (disposing) components.Dispose();   // disposes everything registered above
    base.Dispose(disposing);
}
```

**Why:** several BCL/WinForms components (`NotifyIcon`, `Timer`, …) have a
constructor overload taking an `IContainer` — passing the designer's `components`
field registers the new instance with that container, so `components.Dispose()`
(the designer-generated one-liner every WinForms `Form`/`UserControl` already has)
disposes it. Same idea, different call shape as entry 12.

**Analyzer angle:** the extractor's field-disposal scan doesn't recognise
`new T(components)` or an explicit `components.Add(x)` as wiring `x` into the
`IContainer` disposal chain, so it flags the field as leaked. **Rule of thumb:
construction through (or explicit registration into) the designer's `IContainer`
is a release, exactly like `Controls.Add` — the container's `Dispose()` is the
real sink.**

**Shipped (issue #219 — covers both entries 12 and 13).** The field-disposal scan
now credits both channels, but **only when the class reaches the framework disposal
root** — a designer `Dispose(bool)` that calls `base.Dispose(disposing)`
(`ClassReachesDisposalRoot`). A class with no such Dispose (the ShareX
`HistoryItemManager` true-positive) is not rooted, so its owned controls stay
flagged. (a) A `Control`/`ToolStripItem` field added to **this object's own**
`Controls`/`Items` collection (`this.Controls.Add`/`AddRange`, or `this.<field>.
Items.Add` where `<field>` itself reaches the root) is released transitively — a
fixpoint so a `ToolStrip` added to `this.Controls` cascades to its items. An add
into a **foreign** container (a parameter/local — resolved semantically, not by
name) yields no credit and stays flagged. (b) A field **constructed with** the
designer `IContainer` (`new T(components)`) or explicitly `components.Add(x)` is
released by `components.Dispose()`; the sink is a disposed field of type
`System.ComponentModel.IContainer`. A component **not** registered (a bare
`new NotifyIcon()`) stays flagged. Extractor-only, no OwnIR change. Pinned by
`frontend/roslyn/samples/WinFormsDisposalSample.cs` (six channel-disposed fields
silent; `lblForeign`/`cms`/`item`/`unregisteredIcon` controls flagged) in the
`wpf-extractor` CI job.

## 14. `using (field = new T())` — a field as the direct `using` acquisition target

**Seen in:** ShareX `ShareX.HelpersLib/Cryptographic/HashChecker.cs:59`,
`ShareX.HelpersLib/TaskEx.cs:55`, `ShareX.IndexerLib/IndexerJson.cs:49`. Found by
the issue #201 oracle sweep.

```csharp
private CancellationTokenSource cts;
public void Cancel() {
    using (cts = new CancellationTokenSource()) {   // field IS the using target
        ...
    }
    // cts.Dispose() ran at the end of the using block
}
```

**Why:** a `using (expr) { }` disposes whatever `expr` evaluates to when the block
exits — it doesn't matter whether `expr` is a bare `new T()`, a pre-existing local
(the already-handled `using (preExistingLocal)` shape, `field-dispose-via-*`
fixtures), or, as here, an **assignment to a field**. The field is disposed exactly
once, deterministically, at the end of the block.

**Analyzer angle:** the flow-locals detector's `using`-release recognition is
scoped to a **local** target; a field on the left-hand side of the acquisition
expression inside `using (...)` isn't threaded back to the field-disposal scan, so
the field reads as permanently un-disposed. **Rule of thumb: `using (field = new
T())` releases `field` just as surely as `using (var local = new T())` releases
`local` — the target of a `using` acquisition can be any writable location, not
only a fresh local.**

## 15. Self-owned source reached through a base-class accessor or an owned collection element

**Seen in:** MahApps.Metro `src/MahApps.Metro/Behaviors/TiltBehavior.cs:62-70`
(`panel.Loaded +=` where `panel == this.AssociatedObject`); MaterialDesignInXamlToolkit
`src/MainDemo.Wpf/Domain/ListsAndGridsViewModel.cs:16-17` (`model.PropertyChanged +=`
where `model` is an element of `Items1`, a collection the ViewModel builds itself in
its own constructor). Found by the issue #201 oracle sweep.

```csharp
protected override void OnAttached() {
    this.attachedElement = this.AssociatedObject;      // base-class accessor
    if (this.attachedElement is Panel panel)
        panel.Loaded += (sl, el) => { ... };            // <- flagged
}
```
```csharp
public ListsAndGridsViewModel() {
    Items1 = CreateData();                              // own factory
    foreach (var model in Items1)
        model.PropertyChanged += (s, a) => OnPropertyChanged(...);   // <- flagged
}
```

**Why:** both are variations on the already-recognised self-owned-source
exemption (a class subscribing to something it owns is a collectable cycle, not a
leak) — just reached through a different path than a constructed field: a
`Behavior<T>`'s `AssociatedObject` (the base class's own accessor for the element
the behavior is attached to — necessarily co-lifetimed, since a `Behavior` cannot
outlive being attached), or an element of a collection the class builds itself in
its own constructor/factory (the collection and its elements share the
constructing object's lifetime).

**Analyzer angle:** the shipped self-owned-source exemption keys off a directly
constructed/assigned field; it doesn't follow `this.AssociatedObject` (a
base-class-provided reference, not a locally constructed one) or "an element
pulled from a collection this class itself populated." **Rule of thumb: the
exemption's real criterion is "does this object's lifetime start and end with the
subscriber's" — a base-class accessor to the attached object, or an item of an
owned collection, satisfies that just as well as a constructed field.**

## 16. Template part fetched via `FindName`/`GetTemplateChild`, stored as a local

**Seen in:** MahApps.Metro `src/MahApps.Metro/Controls/MetroWindow.cs:1447-1449`
(`if (this.GetTemplateChild(PART_Content) is MetroContentControl
metroContentControl)`); AvalonEdit `ICSharpCode.AvalonEdit/CodeCompletion/OverloadViewer.cs:58-64`
(`Button upButton = (Button)this.Template.FindName("PART_UP", this);`). Found by
the issue #201 oracle sweep.

```csharp
public override void OnApplyTemplate() {
    base.OnApplyTemplate();
    Button upButton = (Button)this.Template.FindName("PART_UP", this);
    upButton.Click += (sender, e) => { ... };   // <- flagged
}
```

**Why:** a named template part is owned by the control's own template — its
lifetime is bound to the control instance, exactly the shape the shipped
self-owned-template-part exemption already covers (real-world-mining.md's
`GetTemplateChild`/`FindName` fix). The only difference here is where the result
is stored.

**Analyzer angle:** the existing exemption keys off a **field** assignment
(`_field = GetTemplateChild(...) as T`); both examples above store the template
part in a **local** instead (a plain local variable, or an `is T x` pattern
match). Same safe shape, narrower syntactic form the exemption doesn't reach.
**Rule of thumb: "fetched from my own template" is what makes a template part
self-owned — whether the result lands in a field or a method-local variable
doesn't change that.**

## 17. `CommandManager.RequerySuggested` — a BCL/WPF event built on weak references

**Seen in:** AvalonEdit `ICSharpCode.AvalonEdit/Editing/ImeSupport.cs:34-47`.
Found by the issue #201 oracle sweep.

```csharp
EventHandler requerySuggestedHandler; // we need to keep the event handler instance
                                       // alive because CommandManager.RequerySuggested
                                       // uses weak references
requerySuggestedHandler = OnRequerySuggested;
CommandManager.RequerySuggested += requerySuggestedHandler;   // never -=, and that's fine
```

**Why:** `System.Windows.Input.CommandManager.RequerySuggested` is WPF's own
answer to the classic "static event pins every subscriber forever" trap — it's
implemented internally over weak references, so a subscriber is **not** kept
alive by the subscription (the in-repo comment even explains the field exists to
keep the handler *itself* from being collected prematurely, the opposite concern).
Never unsubscribing is the normal, intended usage.

**Analyzer angle:** Own.NET tiers a subscription to a provably `static` source as
a hard **error** ("possible leak" promoted to certain, since a static source
trivially outlives everything) — the systematically wrong verdict for this one
named event. **Rule of thumb: a handful of BCL/WPF statics are deliberately
weak-referenced specifically to be safe to never detach from; treat
`CommandManager.RequerySuggested` (and any future confirmed sibling) as a named
allowlist entry, not a case for the general static-source rule.**

## 18. Self-detaching handler (unsubscribes itself inside its own body)

**Seen in:** AvalonEdit `ICSharpCode.AvalonEdit/Search/DropDownButton.cs:78-86`.
Found by the issue #201 oracle sweep.

```csharp
DropDownContent.Closed += DropDownContent_Closed;   // <- flagged: no visible -=

void DropDownContent_Closed(object sender, EventArgs e) {
    ((Popup)sender).Closed -= DropDownContent_Closed;   // removes itself, first firing
    this.IsDropDownContentOpen = false;
}
```

**Why:** the handler removes itself from the event the first time it runs — a
common one-shot idiom ("do this once, then stop listening") that needs no
external detach call at all. By the time the event could fire a second time, the
subscription is already gone.

**Analyzer angle:** Own.NET's `-=`-search is scoped to the subscribe call's
enclosing method (or a class-level scan for a plain field-based handler); it
doesn't look **inside the handler's own body** for a matching self-removal.
**Rule of thumb: a handler that unsubscribes itself as its first action is
bounded by construction — the search for a matching `-=` needs to include the
handler body, not just sibling code near the `+=`.**

## 19. A user-defined type whose `Dispose()` body is statically empty

**Seen in:** ClosedXML `ClosedXML/Excel/Cells/Slice.cs:324-416` (`internal class
Enumerator : IEnumerator<Point>`). Found by the issue #201 oracle sweep.

```csharp
internal class Enumerator : IEnumerator<Point> {
    ...
    public void Dispose() { }   // literally empty — no base call, no field release
}
// caller:
var enumerator = new Enumerator(this, area);
while (enumerator.MoveNext()) { ... }   // never disposed — flagged
```

**Why:** `Enumerator` implements `IDisposable` only because `IEnumerator<T>`
requires it, not because it holds a real resource — its `Dispose()` does
nothing at all. Never calling it cannot leak anything; there is nothing behind
the interface to release.

**Analyzer angle:** entry 9 already covers this *idea* for a handful of named
**BCL** types (`StringWriter`/`StringReader`, via `IsNoOpDisposeWrapper`), but
that allowlist doesn't reach a **user-defined** type, however trivially empty
its `Dispose()` is. **Rule of thumb: rather than growing a list of known-safe
type names, a `Dispose()` method whose body is provably empty (no statements)
is safe to skip regardless of whose type it is — first-party or third-party,
named allowlist or not.**

**Shipped (issue #225).** `HasEmptyDisposeBody` (extractor) recognises a type
whose parameterless `Dispose()` is declared in source with a **block body of zero
statements** *and* whose base chain carries no `Dispose` to cascade to (base is
`object` / not `IDisposable`), so nothing real is skipped. A **LOCAL** of such a
type never disposed is then dropped from both the flat (`IsDisposableType`) and the
`--flow-locals` (`ImplementsIDisposable`) local-disposable paths. Deliberately
**scoped to locals**: a FIELD keeps its own disposal contract (so the
`OwnIgnoreSample` `Handle` field stand-in and other field fixtures are untouched).
Precision guards, each pinned by `EmptyDisposeSample.cs`: a **non-empty** body
(`RealResource`, `LeakyReader`) still leaks; an **empty override over a base whose
`Dispose` does real work** (`EmptyOverrideOverRealBase`) still leaks; an
**expression-bodied / metadata-only** `Dispose` we cannot read as empty is not
exempted (never a guessed drop). The empty enumerator (`EmptyDisposeEnumerator`,
the ClosedXML shape) and an empty `*Reader` (`ScratchReader`) stay silent. Two
existing fixtures that had used an empty `Dispose()` as a modelling shortcut
(`UnitOfWork`, `PixelOwner`) were made faithful (a real Dispose body) so they
remain genuine leak fixtures.

---

## The through-line

Entries 1–6 are the *same lesson from different angles*: **disposal
responsibility travels with the reference** — out of a factory (1, 6), forward in
time via a callback (2), into a pool (3), or down a `using` on a value type (4).
Naive "every disposable needs a lexical `using`/`Dispose` on every path" checks
misread all of them, which is why Infer#/CodeQL over-report here and a
transfer/escape-aware checker (Own.NET) correctly stays quiet. (Entry 7 is a run
ledger — an audit record of a Polly re-run, not an idiom.)

Entries 8–9 are the **mirror image — the first cases where _Own.NET_ is the one
over-reporting and the oracle is correctly silent.** They map our own precision
frontier: a subscription on a publisher that *escapes by return* (8, the dual of
ownership transfer — bounded, but the construct-and-return is interprocedural), and
an owning field whose `IDisposable` holds no real resource (9, a `StringWriter` is
not a handle — belongs in the `IsDisposeOptional` allowlist). Same moral as 1–6,
pointed back at us: **a leak is about the *resource* and the *reference's
lifetime*, not the mere presence of an `IDisposable` and a missing `Dispose`/`-=`.**
Worth learning as C#; worth pinning as the precision frontier.

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
