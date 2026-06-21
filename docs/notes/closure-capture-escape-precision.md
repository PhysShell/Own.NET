# Closure-capture escape — a local captured by a lambda is not method-bounded

A precision fix driven by triaging the **re-mine of ShareX** (after the WinForms
modeless-`Form` fix, #57): of the seven local-disposable findings that survived, six
were real or defensible and **one was a false positive** — `Helpers.ForEachAsync`'s
`SemaphoreSlim throttler`:

```csharp
public static Task ForEachAsync<T>(IEnumerable<T> items, Func<T, Task> body, int max)
{
    SemaphoreSlim throttler = new SemaphoreSlim(max, max);

    IEnumerable<Task> tasks = items.Select(async input =>
    {
        await throttler.WaitAsync();                 // throttler used INSIDE the lambda
        try { await body(input); } finally { throttler.Release(); }
    });

    return Task.WhenAll(tasks);                       // the lambdas (and throttler) escape
}
```

The flow detector saw `throttler = new SemaphoreSlim(...)` (an undisposed `IDisposable`
local) and flagged OWN001. But `throttler` is **captured by the async lambdas**, and
those lambdas escape the method — they run while the returned `Task.WhenAll(tasks)` is
awaited by the caller. The semaphore must stay alive until every task finishes, so it
*cannot* be disposed at method scope. It is not a method-local leak.

## The fix — capture into a closure is an escape

The flow detector already untracks a local that escapes by **return**, **out/ref**, or
being **passed as an argument** (an ambiguous ownership transfer). A capture into a
closure is the same kind of escape — the closure can be stored, returned, or run async,
so the local outlives the method frame. The escape filter now also untracks a candidate
local when any reference to it is **lexically inside a lambda / anonymous method / local
function** body:

```csharp
// in the --flow-locals escape filter, before the return/out/arg checks:
var capturedInClosure = false;
for (var a = idn.Parent; a is not null && a != mbody; a = a.Parent)
    if (a is AnonymousFunctionExpressionSyntax or LocalFunctionStatementSyntax)
    { capturedInClosure = true; break; }
if (capturedInClosure) { escapedLocals.Add(nm); continue; }
```

It is purely syntactic (an ancestor walk to the method body), so it is crash-proof and
needs no escape/data-flow analysis of where the closure goes. It deliberately does **not**
require proving the closure escapes: a captured local *may* outlive the method, and the
precision-first stance is to not flag what we cannot prove leaks.

### Why not just exempt `SemaphoreSlim`?

`SemaphoreSlim` is **not** unconditionally dispose-optional: accessing
`AvailableWaitHandle` lazily allocates a wait handle that `Dispose()` must release (CA2000
flags an undisposed one). Blanket-exempting it (the way `Task`/`DataTable` are exempt in
`IsDisposeOptional`) would be unsound — it would hide a real method-local semaphore leak.
The bug here is the **capture/escape**, not the type, so the fix targets the capture.

## The recall trade-off (sound, bounded)

The rule is conservative: a local captured by a closure that does **not** escape, and is
never disposed, is now silenced too (e.g. `var s = new MemoryStream(); Action a = () =>
s.Use(); a(); /* never disposed */`). Proving such a closure stays method-local is exactly
the data-flow analysis the syntactic rule avoids, so this is an accepted recall gap, never
a false positive — the same precision-over-recall trade the escape filter already makes for
argument-passing.

## Pinned in CI

`frontend/roslyn/samples/FlowLocalsSample.cs` gains two cases, asserted in the
`wpf-extractor` `--flow-locals` step:

- `ThrottlerCaptured` — a `SemaphoreSlim` captured by a returned async lambda → **silent**
  (the FP this removes);
- `SemaphoreLeaks` — a `SemaphoreSlim` **not** captured by any closure and never disposed →
  **OWN001**, proving the exemption is closure-capture, not a blanket `SemaphoreSlim`
  dispose-optional.

The existing `UnitOfWorkFlowSample` OWN001 is unaffected: its `uow` is always the
*receiver* of `uow.Member` (outside the `.Where(p => …)` lambda bodies, which reference
`p`), and the `join … in uow.TempProducts` is query syntax, not an
`AnonymousFunctionExpressionSyntax` — so the ancestor walk never marks `uow` captured.
