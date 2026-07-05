# P-026 — Dispatcher/Task continuation capture leak (`WPF006`)

- **Status:** draft.
- **Depends on:** [P-001](P-001-csharp-extractor.md) (the extractor + OwnIR
  seam), [P-004](P-004-wpf-lifetime-profile.md) (WPF001–005 — specifically the
  WPF005 region-escape mechanism this proposal reuses), `spec/Lifetimes.md`
  (OWN014 region escape). **Distinct from** [P-021](P-021-async-audit-pack.md)
  (`Own.Async`) — see "Why not P-021 / P-004 as-is" below.

## Motivation

A real, frequently-reported WPF leak shape that neither existing proposal
models: a lifetime-bound component (ViewModel/View/Window) schedules a closure
onto infrastructure that outlives it, and the closure captures `this`.

```csharp
public class DeclarationViewModel : ViewModel
{
    public void RefreshLater()
    {
        // captures `this` into the Dispatcher queue. If the window closes
        // before this fires, the VM is pinned until the dispatcher drains it.
        Dispatcher.CurrentDispatcher.BeginInvoke(new Action(() =>
        {
            LoadSummary();
            OnPropertyChanged(nameof(Summary));
        }));
    }

    public void PollStatus()
    {
        // never terminates on its own — re-schedules itself every tick.
        // Closing the window does not stop the chain; the VM lives until
        // process exit or an explicit CancellationToken this code never checks.
        Task.Delay(1000).ContinueWith(_ =>
        {
            RefreshStatus();
            PollStatus();
        }, TaskScheduler.FromCurrentSynchronizationContext());
    }
}
```

Both patterns are in the source proposal's checklist ("Dispatcher.BeginInvoke
closures", "Task.ContinueWith holding this") and are not exotic — polling
status bars, deferred UI refresh after a heavy load, and "retry in N seconds"
are common legacy-WPF idioms. Unlike an event subscription, there is no
`+=`/`-=` pair to check for: the leak is *implicit* in scheduling a closure
that captures a long-lived reference onto infrastructure (`Dispatcher`,
`ThreadPool`/`TaskScheduler`) that is itself process-lived.

## Why not P-021 / P-004 as-is

- **P-021 (`Own.Async`)** models `async`/`await` *correctness* — a returned
  `Task` escaping a `using`/`try-finally` scope, blocking waits, `async void`,
  ignored tasks. None of its hazards model an *anonymous closure escaping to a
  longer-lived scheduler*; `ASYNC001`/`ASYNC002` are about the resource the
  method itself owns, not about what the method hands off to Dispatcher/TPL
  infrastructure. A `Dispatcher.BeginInvoke(() => ...)` call has no `async`
  keyword and returns `void`/`DispatcherOperation` — it never touches P-021's
  fact family at all.
- **P-004 (WPF lifetime profile)** already solved the *general shape* this
  needs — WPF005's `capture` fact + region-escape engine, used today for a
  static-event `+=`. But its extractor only recognises `+=` as the capture
  site. `Dispatcher.BeginInvoke`/`InvokeAsync` and `Task.ContinueWith` are a
  *second* capture site with the same "escapes to a process-lived region"
  shape, requiring closure-body capture analysis instead of an event operator.

So this is a new rule number (`WPF006`) under the existing P-004 *mechanism*,
proposed separately because the extractor work (recognising closure captures
of `this`/instance fields passed to specific BCL sink methods) is a distinct
increment, not a copy-paste of WPF001–005.

## Scope

Recognised in the same lifetime-bound components as P-004 (name heuristic:
ends `ViewModel`/`View`, derives `Window`/`UserControl`/`Page`, implements
`INotifyPropertyChanged`).

| Sink | Pattern | Region |
|------|---------|--------|
| `Dispatcher.BeginInvoke` / `Dispatcher.InvokeAsync` / `this.Dispatcher.BeginInvoke` | lambda/delegate argument closes over `this` or an instance field | `Dispatcher` (process-lived) |
| `Task.Run(...).ContinueWith(...)` / `.ContinueWith(..., TaskScheduler.FromCurrentSynchronizationContext())` | continuation lambda closes over `this` or an instance field | `TaskScheduler`/`ThreadPool` (process-lived) |
| `Task.Delay(...).ContinueWith(...)` used as a polling/retry loop | as above, **plus** the continuation re-invokes the same method (self-rescheduling) | as above, escalated severity |

Two confidence tiers, mirroring WPF005's split by source lifetime:

- **`WPF006` (error)** — a **self-rescheduling** closure (the continuation
  calls back into a method that re-arms the same `BeginInvoke`/`ContinueWith`)
  with no observed `CancellationToken` check or a lifecycle guard
  (`IsDisposed`/`IsLoaded`-style flag) inside the closure body. This chain has
  no natural termination — the component leaks until process exit, which is
  the "worst case" the source proposal calls out (`PollStatus` above).
- **`WPF006` (warning)** — a **one-shot** deferred closure with no matching
  cancellation registered in `Dispose`/`OnClosed`/`Unloaded` (a
  `CancellationTokenSource` field cancelled there, or a `DispatcherOperation`
  handle `.Abort()`'d there). Bounded (fires once, then releases), so lower
  severity than the self-rescheduling case, but still worth flagging — the
  window can close and reopen many times before the deferred callback fires,
  and each one is a live capture until it does.

A closure with a **captured local guard checked first**
(`if (_isDisposed) return;`) is not silenced automatically — that guard
prevents the *work* from running, not the *retention* (the delegate and its
captured `this` are still queued and reachable) — but it does downgrade
confidence, since it signals the author already thought about the lifecycle.

## Non-goals

- No general TPL dataflow or `Task` continuation graph. One hop
  (`BeginInvoke`/`ContinueWith` call site → its own lambda body) only; a
  continuation that calls a named method (not a lambda) is not inspected
  inside that method (no interprocedural closure tracing in v1).
- No modelling of `SynchronizationContext.Post`/`Send` beyond the two BCL
  sinks above in v1 — same shape, later increment if it proves common.
- No attempt to verify a `CancellationToken` is *actually checked* on every
  path inside the closure — presence of a token parameter/field passed to the
  sink is enough evidence to downgrade confidence, not a soundness proof.
- No autofix. The fix (store a `CancellationTokenSource`, cancel it in
  `Dispose`/`OnClosed`, check `IsCancellationRequested` before rescheduling)
  is a judgement call about which lifecycle hook exists in a given legacy
  class; Own.NET reports the evidence, a human wires the cancellation.
- Does not replace `ASYNC010`/`ASYNC030` (P-021) — an `async void` polling
  loop or an ignored fire-and-forget `Task` are still that proposal's rules;
  this one is specifically about closures escaping to Dispatcher/TPL and
  capturing a lifetime-bound `this`.

## Sketch

Reuses the WPF005 mechanism end to end — a new extractor recognizer, the same
core region engine:

```text
*.cs --[extractor: closure arg to Dispatcher.BeginInvoke/InvokeAsync or
         Task.ContinueWith, capturing `this`/instance field]--> capture fact
     --[core: region engine, same as WPF005]--> OWN014-family verdict @ line
     --[self-rescheduling detector: continuation calls an enclosing/sibling
         method that re-arms the same sink]--> escalate to error
```

OwnIR shape — a `capture` fact tagged by sink kind, parallel to WPF005's
static-event capture:

```json
{
  "captures": [
    {
      "kind": "dispatcher-continuation",
      "sink": "Dispatcher.BeginInvoke",
      "file": "DeclarationViewModel.cs",
      "line": 14,
      "captured": "this",
      "self_rescheduling": false,
      "cancellation_evidence": "none"
    }
  ]
}
```

`self_rescheduling: true` and `cancellation_evidence: "none"` together select
the error tier; either evidence for cancellation (a `CancellationTokenSource`
field cancelled in a `Dispose*`/`OnClosed`/`Unloaded` method, or a guard flag
checked at the top of the closure) downgrades to warning or drops the finding
below the report's severity floor, per the profile.

## Acceptance fixtures

- Bad (error): `PollStatus`-shaped self-rescheduling `Task.Delay(...).ContinueWith(_ => { ...; PollStatus(); })`
  with no `CancellationToken` anywhere in the class.
- Bad (warning): a one-shot `Dispatcher.BeginInvoke(() => { LoadSummary(); })`
  in a class with a `Dispose()` that does not cancel or guard it.
- Good (silent): the same one-shot call, but `Dispose()` sets `_disposed = true`
  and the closure's first line is `if (_disposed) return;` *and* the class
  additionally holds/cancels a `CancellationTokenSource` — full lifecycle
  evidence.
- Good (silent): `Dispatcher.BeginInvoke` called on a `static`/singleton
  service class (not a lifetime-bound component per the P-004 heuristic) —
  same self-owned exemption logic as WPF001.

## Open questions

1. Does the self-rescheduling detector need real interprocedural reach (the
   continuation calls a *different* method than the one that scheduled it,
   which itself reschedules), or is same-method / same-class recursion enough
   for v1? Leaning: same-class only, escalate later if the corpus shows
   cross-class chains.
2. Is a captured `CancellationToken` *parameter* (passed in from outside, not
   owned by this class) sufficient evidence to silence the finding, or does
   ownership matter here the way it does for DI captive dependencies (P-006)?
   Leaning: presence is enough for v1 — this rule is about retention evidence,
   not proving the token is honoured.
3. Should `SynchronizationContext.Post/Send` be folded into the same rule now
   or deferred? Leaning: defer — confirm `WPF006` earns its keep on
   `Dispatcher`/`Task.ContinueWith` first (bug-driven expansion, per the
   project's design philosophy), then widen the sink list.
4. Where does this land in the `Plan.md` §2 audit-orchestrator category table
   (the *other* half of the project)? Proposed: a new sub-case of category 2
   (event/subscription leak), since it is the same "capture escapes to a
   longer-lived owner" family, confirmed the same way (leak-harness open/close
   scenario, §4.1) once the extractor slice exists.
