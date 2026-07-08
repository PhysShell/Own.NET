# P-027 — Resource state machines & stale-async-write detection (extends `Own.Async`)

- **Status:** draft — proposal for discussion, not a committed design. Recorded on
  the record so the idea isn't lost, not "we are building this next."
- **Depends on:** [P-021](P-021-async-audit-pack.md) (`Own.Async` — the sibling
  catalog this slots into), [P-020](P-020-ownts-react-effects.md) (`Own.React` —
  the OwnTS mirror of the same lifecycle shape), [P-010](P-010-type-disciplines.md)
  (typestate/protocols — the heavier-weight cousin this deliberately does not
  become), [P-004](P-004-wpf-lifetime-profile.md)/[P-005](P-005-idisposable-ownership.md)
  (subscription/`IDisposable` cleanup — already-covered ground this reuses rather
  than reinvents), [P-025](P-025-obligation-protocols.md) (obligation protocols —
  a plausible home for the in-flight-guard check).

## Origin and honest framing

This proposal started from a critique of a React `useEffect` blog post. The post's
headline advice — "your code should always work without the dependency array" —
is wrong on its own terms: the dependency list is part of `useEffect`'s
synchronization contract with React (it's exactly what `react-hooks/exhaustive-deps`
checks), not an optional optimization to delete. But the critique's *real* kernel
is right, and it has nothing to do with React specifically:

> A resource's lifecycle (empty / loading / available / failed) should be modeled
> as one explicit state, not reconstructed at read time from a pile of booleans
> and a nullable field that also means "not loaded yet."

That kernel generalizes cleanly to any .NET code that loads a resource
asynchronously and drives state off ad hoc flags — WPF ViewModels, Presenters,
Blazor components, service classes:

```csharp
private bool _isLoading;
private bool _isLoaded;
private Customer _customer;   // null: not loaded? loading? load failed?

public async Task LoadAsync()
{
    if (!_isLoaded && !_isLoading)
    {
        _isLoading = true;
        _customer = await _repository.GetCustomerAsync(_customerId);
        _isLoaded = true;
        _isLoading = false;
    }
}
```

This is the same animal P-020 already names for the OwnTS/React side (effect
re-entry, missing cleanup) and P-021 already partly covers for .NET async
(blocking waits, `async void`, task escaping a `using`/`finally`). What neither
proposal covers yet is the *state-shape* problem itself, and its most common
correctness consequence: a **stale write** when the resource identity changes
while the `await` is in flight.

**What this proposal is not**: a rewrite of the source critique's tone or its
"always fail without the second `useEffect` argument" claim. Both are wrong and
out of scope. The only thing worth taking from that text is the two diagnostic
ideas below — everything else in it (dependency-array rhetoric, a proposed
runtime `ResourceState<T>` helper as gospel) is either already someone else's job
in this project or not this project's job at all.

## What's already covered elsewhere (do not reinvent)

Following the "honest split" discipline P-020 already established, most of the
patterns in the source material map onto existing Own.NET ground:

| Pattern in the source critique | Already covered by |
|---|---|
| Missing `-=`/`Dispose()`/`Unsubscribe()` for an event/timer/subscription | `OWN001` (P-004/P-005), and its OwnTS mirror `EFF003`–`EFF005` (P-020) |
| `Task` escaping a `using`/`try`-`finally` scope | `ASYNC001`/`ASYNC002` (P-021) |
| Blocking `.Result`/`.Wait()` on the UI thread | `ASYNC010` (P-021) |
| `async void` outside an event handler | `ASYNC020` (P-021) |
| Fire-and-forget without observation | `ASYNC030` (P-021) |
| Proving valid state *transitions* with consume-self semantics (a `Connection<Closed\|Open>`-style protocol) | typestate/`protocol` blocks (P-010) — deliberately heavier machinery than this proposal wants |

This proposal only adds the **two genuinely new** dimensions: state-shape
normalization, and stale-write protection. If it turns out either is just a
restatement of something above, that's a reason to fold it in, not to ship a
duplicate checker — the project's standing rule is one core, no parallel
verdict engines.

## Scope — two new diagnostics

### 1. Boolean/nullable state soup

A resource's lifecycle is a small state space (`Empty`, `Loading`, `Available`,
`Failed` — sometimes `Cancelled`/`Refreshing`). Representing it as N independent
boolean or nullable fields lets the compiler accept states that shouldn't exist
(`IsLoading == true && IsLoaded == true`), and pushes every reader ("has this
loaded yet?") into reconstructing the state from field combinations instead of
reading one value.

Detect: a cluster of ≥3 boolean/nullable-reference fields that are all assigned
inside the same async-loading method (heuristically: a method that both sets one
of the fields and `await`s something), read together in `if`/`&&` conditions
elsewhere in the same type.

```csharp
// flagged: 4 fields modeling one lifecycle
private bool _isLoading;
private bool _isLoaded;
private Customer _customer;    // doubles as "has value" via null
private Exception _loadError;
```

```text
ASYNC050: fields 'IsLoading', 'IsLoaded', 'Customer' (null-as-status), 'LoadError'
appear to model a single resource lifecycle as independent flags. Combinations
like IsLoading == true && IsLoaded == true are representable but meaningless.
Consider one explicit status (e.g. an enum: Empty/Loading/Available/Failed).
```

Suggested replacement is explanation-only in v0 (see Non-goals) — a comment
pointing at the shape, not an autofix:

```csharp
private enum LoadStatus { Empty, Loading, Available, Failed }
private LoadStatus _status;
private Customer _customer;
private Exception _loadError;
```

### 2. Stale async write / missing in-flight guard

The sharper bug: a value read *before* an `await` gates what gets written
*after* it, but nothing proves the world hasn't moved on while the method was
suspended.

```csharp
public async Task LoadCustomerAsync()
{
    var customer = await _repository.GetCustomerAsync(_customerId); // _customerId read before await
    CurrentCustomer = customer;                                     // written after await
}
```

If `_customerId` changes (user picks a different row) while the first call is
still in flight, the stale response can overwrite the fresher one — or a second
concurrent call starts because nothing checked "am I already loading?" first.
This is the same failure class as the Cloudflare-dashboard effect-storm P-020
already cites, just on the read/write-race axis instead of the re-trigger axis.

Detect two sub-shapes:

- **No in-flight guard (`ASYNC051`)**: an async loading method with no
  early-return/guard against re-entry while a status field is already
  `Loading`, and no synchronization (`SemaphoreSlim`, `lock` around a flag,
  `CompareExchange`) preventing two concurrent calls from both proceeding.
- **No staleness check (`ASYNC052`)**: a field read before an `await` is used
  (directly, or via a captured local) to decide what a field write after the
  `await` commits, with no `CancellationToken`, no version/request-id
  comparison, and no re-read/compare of the gating field after the `await`.

```text
ASYNC051: 'LoadCustomerAsync' starts an async operation with no guard against
re-entry. If called again before the first call completes, both calls will
proceed concurrently. Guard on a status field (e.g. 'return if Status != Empty')
or a synchronization primitive before starting the operation.

ASYNC052: 'LoadCustomerAsync' reads '_customerId' before the await and writes
'CurrentCustomer' after it, with no CancellationToken, version check, or
re-read of '_customerId' in between. If '_customerId' changes while this call
is in flight, a stale response can overwrite fresher state.
```

Both codes are heuristic/evidence-tiered, in the same spirit as P-021's
detectability matrix — high confidence when the guard/version-check is provably
absent syntactically, lower confidence (or silent) when a helper method or
`SemaphoreSlim` field exists nearby and the extractor can't yet prove it's used
correctly.

## Non-goals

- **Not a general data-race detector.** No happens-before model, no full
  shared-mutable-state analysis. Scope stays "resource load method reads before
  an `await`, writes after it, with no visible guard" — a syntactic pattern, not
  a soundness proof.
- **No shipped runtime type.** Own.NET does not ship a `ResourceState<T>`
  NuGet package as the mandated fix, matching P-010's existing rule that
  brands/refinements/protocols lower to plain structs the *team* owns. The
  diagnostic explains the pattern; teams write their own status type (or adopt
  whichever shape fits their codebase).
- **Not typestate.** Proving that `Loading → Available` is the *only* valid
  transition, with consume-self semantics, is P-010's `protocol` block. This
  proposal only flags "these fields look like an unmodeled lifecycle" — a lint,
  not a proof.
- **No duplicate of `OWN001`/`ASYNC001`/`ASYNC002`/`ASYNC010`/`ASYNC020`/`ASYNC030`.**
  Cleanup, blocking waits, `async void`, task-escape, and fire-and-forget stay
  exactly where P-004/P-005/P-020/P-021 already put them.
- **No claim of catching every stale-write race.** Silent by default whenever a
  synchronization primitive or cancellation token is present, even if its use
  can't yet be proven correct — false negatives over false positives, same
  posture as the rest of the async pack.

## Sketch

Same seam as the rest of the project — the Roslyn extractor emits facts, the
Python core emits verdicts:

```text
*.cs --[Roslyn extractor]--> facts.ownir.json --[Python core]--> ASYNC050..052
```

`ASYNC051`/`ASYNC052` are per-method and most likely land as two more hazard
kinds in the `async_methods` fact family P-021 plans (its proposed
`ownlang/async_rules.py` module). `ASYNC050` is type-scoped — a cluster of fields
assigned together across the whole class, not one method — so it needs its own
type-level fact rather than living inside a method entry:

```json
{
  "types": [
    {
      "id": "CustomerViewModel",
      "status_field_clusters": [["_isLoading", "_isLoaded", "_loadError"]]
    }
  ],
  "async_methods": [
    {
      "id": "CustomerViewModel.LoadCustomerAsync",
      "await_count": 1,
      "reads_before_await": ["_customerId"],
      "writes_after_await": ["CurrentCustomer"],
      "has_cancellation_token": false,
      "has_version_check": false,
      "guarded_fields": [],
      "hazards": [
        { "kind": "no_inflight_guard", "line": 40 },
        { "kind": "stale_write_no_guard", "line": 41, "read": "_customerId", "written": "CurrentCustomer" }
      ]
    }
  ]
}
```

`types[].status_field_clusters` feeds `ASYNC050` independently of the
per-method `hazards`, keeping the type-level and method-level extractor
contracts separate.

## Open questions

1. **Home for the codes.** Extend P-021's `ASYNC0xx` family (leaning: yes — same
   audience, same fact shape, same team owns both), or a separate prefix so
   "state soup" doesn't read as an async-specific bug even when the loading path
   happens to be synchronous? Leaning toward `ASYNC05x` since the motivating
   cases are overwhelmingly async load methods.
2. **Threshold for state soup.** Two co-varying fields (`HasValue`/`Value`) are
   completely ordinary and shouldn't fire. Where's the real line — 3 fields? A
   specific combination like `bool + bool + nullable`? This needs corpus
   evidence (P-012) rather than a guessed constant, in the same evidence-first
   spirit as P-021.
3. **Staleness-check feasibility.** Proving "the gating field was re-read or a
   version was compared between the pre-await read and the post-await write"
   needs more than single-method syntax — it's adjacent to P-016's deep fact
   extraction (CFG across the `await` boundary). Does `ASYNC052` start as a
   narrower syntactic pattern (a specific field/property re-read immediately
   before the write) and grow into real flow evidence later, same staging P-016
   already uses elsewhere?
4. **Does the in-flight guard belong to P-025 instead?** "Must not start a new
   load while `Status == Loading`" is exactly a barrier-sensitive temporal
   obligation — P-025's `OBL` machinery already models "call A before call B,
   guarded by a barrier." `ASYNC051` may be P-025's first non-toy consumer
   rather than a bespoke check; worth prototyping against `OBL` before writing a
   parallel guard-detector.
5. **Suggested-fix surface.** Stay explanation-only (a diagnostic message
   pointing at the shape) in v0, or eventually offer a code-fix snippet for the
   `enum`-based replacement? Leaning: explanation-only until the pattern proves
   out on real code, matching P-021's own "no mass autofix" stance for
   `ASYNC040`.
