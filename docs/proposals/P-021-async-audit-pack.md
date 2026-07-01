# P-021 — Async audit pack (`Own.Async`)

- **Status:** draft — feasibility and MVP plan accepted; implementation not started.
- **Depends on:** [P-001](P-001-csharp-extractor.md) (C# → OwnIR extractor),
  [P-004](P-004-wpf-lifetime-profile.md) (WPF / UI lifetime profile),
  [P-005](P-005-idisposable-ownership.md) (`IDisposable` ownership),
  [P-015](P-015-configuration-surface.md) (check selection / severity), and
  [P-016](P-016-deep-fact-extraction.md) (deep C# fact extraction). Relates to
  [P-008](P-008-effects-and-resources.md) where async effects later become part
  of the broader effect/resource interface.

## Motivation

Most async analyzers are good at spotting syntax and weak at preserving intent.
The common example is the `async`/`await` elision rule: a method shaped like
`return await inner;` can often return `inner` directly, but the choice is not
pure style. Keeping `await` may preserve exception timing, diagnostic stack
boundaries, resource lifetime, `try/finally` ordering, UI continuation semantics,
and logical context behaviour.

Own.NET should not build another warning generator that says "unnecessary
`await`" because a syntax pattern matched. The value proposition is narrower and
stronger:

> **Own.Async finds async lifecycle and UI-threading bugs where the evidence is
> visible, and treats async elision as a review suggestion, not a verdict.**

This fits the project's identity: lifetime/resource/effect contracts that C#
cannot express, checked by one core, with Roslyn extracting facts rather than
issuing its own verdicts.

## Scope

The first shipped shape is a safety-first WPF/application async pack. It should
prioritise code that can break correctness or production diagnostics over code
that merely allocates an async state machine.

### MVP diagnostics

| Code | Finding | Default severity | Confidence |
|------|---------|------------------|------------|
| `ASYNC001` | Returned `Task` escapes a disposable / `using` scope | error/warning | deterministic when receiver/resource use is proven |
| `ASYNC002` | Returned `Task` escapes a `try/finally` or busy-state scope, so cleanup runs before completion | error/warning | deterministic for syntactic `try/finally`; heuristic for state names |
| `ASYNC010` | Blocking wait on `Task` in UI-sensitive code (`.Result`, `.Wait()`, `.GetAwaiter().GetResult()`) | error in UI profile, warning elsewhere | heuristic, evidence-tiered |
| `ASYNC020` | `async void` outside recognised event-handler shapes | error | deterministic enough for method shape + event-handler exemptions |
| `ASYNC030` | Ignored `Task` / fire-and-forget without observation or an approved helper | warning/error by profile | heuristic with suppression/helper configuration |
| `ASYNC040` | Trivial async passthrough candidate | info | deterministic syntax, advisory only |

The diagnostic family deliberately starts at `ASYNC###` rather than overloading
`OWN###`: the root engine remains the ownership/lifetime/effect checker, but
these findings are async-contract verdicts over an additive fact family, like DI
and React effect findings.

### First implementation slice

Build `ASYNC001` first:

```csharp
public Task<string> BrokenAsync(string url)
{
    using var client = new HttpClient();
    return client.GetStringAsync(url);
}
```

The returned `Task` may continue after `client` has been disposed. The safe shape
keeps the await inside the resource scope:

```csharp
public async Task<string> SafeAsync(string url)
{
    using var client = new HttpClient();
    return await client.GetStringAsync(url);
}
```

This is the best first slice because it is close to Own.NET's existing resource
identity, visible with syntax plus `SemanticModel`, and does not start with a
subjective style rule.

## Non-goals

- No full C# async semantics or compiler-equivalent async state-machine model.
- No whole-program call graph.
- No blanket "use `ConfigureAwait(false)`" rule.
- No mass autofix for async elision.
- No Roslyn-side verdict engine. The extractor emits facts; the Python core owns
  findings.
- No attempt to infer every possible `AsyncLocal`, tracing, logging, activity, or
  diagnostic-boundary reason for retaining `await`.
- No promise to classify all fire-and-forget intent without project
  configuration.

## Sketch

The seam stays the same deep module interface the rest of Own.NET uses:

```text
*.cs --[Roslyn extractor]--> facts.ownir.json --[Python core]--> ASYNC001..ASYNC040
```

The Roslyn extractor performs local, type-aware fact extraction. The Python core
validates an optional async fact family and emits verdicts. This keeps the
implementation local and preserves the "one checker" rule.

### OwnIR fact shape

The async pack adds an optional top-level `async_methods` array. Because it is
additive, it should not require an OwnIR version bump unless the vocabulary later
changes incompatibly.

```json
{
  "async_methods": [
    {
      "id": "SubjectPresenter.LoadAsync",
      "file": "SubjectPresenter.cs",
      "line": 42,
      "layer": "wpf-viewmodel",
      "is_async_keyword": true,
      "returns_task_like": true,
      "returns_void": false,
      "await_count": 1,
      "has_configure_await_false": false,
      "hazards": [
        {
          "kind": "returned_task_escapes_using",
          "line": 47,
          "resource": "client",
          "operation": "client.GetStringAsync",
          "scope_line": 45
        }
      ]
    }
  ]
}
```

Minimal fields:

- `id`: stable method identity, preferably including containing type.
- `file` / `line`: primary method location.
- `layer`: optional UI/service/test/infrastructure classifier evidence.
- `is_async_keyword`, `returns_task_like`, `returns_void`, `await_count`: method
  shape facts.
- `hazards`: fact-level evidence extracted by Roslyn, not a final verdict.

The first hazard kinds:

| Hazard kind | Core diagnostic | Required evidence |
|-------------|-----------------|-------------------|
| `returned_task_escapes_using` | `ASYNC001` | returned invocation line, scoped resource, scope line |
| `returned_task_escapes_finally` | `ASYNC002` | return line, finally line, cleanup operation label |
| `blocking_wait` | `ASYNC010` | call/member line, wait shape, UI evidence if any |
| `async_void_non_event` | `ASYNC020` | method line, why event-handler exemption did not apply |
| `ignored_task` | `ASYNC030` | call line, callee name, observation/helper evidence |
| `trivial_async_passthrough` | `ASYNC040` | await line, inner call, absence of blocking evidence |

### Core module

Add a small core module, for example `ownlang/async_rules.py`, analogous in role
to the DI and effect analyses. It should:

1. Shape-check async facts defensively.
2. Convert fact-level hazards into `Finding` instances.
3. Attach reachability slices when two locations explain the bug, such as
   `using` acquisition/scope line -> returned task line.
4. Apply severity policy from the profile/configuration layer when P-015 grows
   enough surface.

The core should not lower every async hazard into ownership statements. Some
cases, especially `ASYNC001`, may later reuse ownership/lifetime machinery, but
the MVP can be a separate analysis over async facts as long as verdict ownership
stays in Python.

## Detectability matrix

| Pattern | Static confidence | Why |
|---------|-------------------|-----|
| `using var x; return x.Async()` | high | scope and receiver are local and visible |
| `try { return task; } finally { cleanup; }` | high | `finally` ordering is syntactic |
| `.Result` / `.Wait()` in WPF ViewModel/event handler | medium-high | blocking wait is syntactic; UI path is heuristic/profile evidence |
| `async void` public/business method | high | method shape is direct; event-handler exemptions are finite |
| ignored `Task` | medium | observation intent may be project-specific |
| trivial async passthrough | high as syntax, low as policy | safe to suggest, unsafe to autofix blindly |
| `AsyncLocal` leakage | low | usually semantic/logical context, not local syntax |
| lost stack-trace boundary | low/subjective | valuable explanation, not a build-breaking verdict |

## Severity policy

Default severities should be profile-aware:

- **Error / high warning**:
  - `ASYNC001` when the returned task provably uses a scoped disposable.
  - `ASYNC002` when `finally` cleanup is clearly intended to run after completion.
  - `ASYNC010` inside WPF UI event handlers, command handlers, Views, ViewModels,
    or Dispatcher-bound code.
  - `ASYNC020` outside event handlers.
- **Warning**:
  - `ASYNC030` ignored tasks without approved helpers.
  - `ASYNC010` outside a known UI path.
- **Info**:
  - `ASYNC040` trivial async passthrough. No autofix by default.

## Async elision stance

Own.Async must not repeat the mistake of treating `async`/`await` as unnecessary
because the wrapper appears to pass through a call. The rule is:

```text
Return Task directly only when the method is a trivial passthrough and no evidence
suggests changed exception timing, resource lifetime, cleanup ordering, UI context,
diagnostic boundary, or logical context behaviour.
```

So this is an info-only finding:

```csharp
public async Task<User> GetUserAsync(int id)
{
    return await repo.GetUserAsync(id);
}
```

But these should not get elision suggestions:

```csharp
public async Task<User> GetUserAsync(int id)
{
    Validate(id);
    return await repo.GetUserAsync(id);
}
```

```csharp
public async Task SaveAsync()
{
    BeginBusy();
    try
    {
        await service.SaveAsync();
    }
    finally
    {
        EndBusy();
    }
}
```

For application, business, API, and WPF code, keeping `await` for diagnostic and
semantic clarity is an acceptable design choice. Own.Async may explain the trade,
but it should not fail a build for it.

## Acceptance fixtures

The first fixtures should be source-level C# samples under the Roslyn extractor
sample set plus hand-written OwnIR facts for the Python bridge.

### `ASYNC001`

- Bad: `using var client = new HttpClient(); return client.GetStringAsync(url);`
  emits `ASYNC001`.
- Good: `using var client = new HttpClient(); return await client.GetStringAsync(url);`
  stays silent.
- Good: `return repo.GetUserAsync(id);` with no scoped disposable stays silent.
- Good: `using var stream = Open(); await writer.WriteAsync(stream); return;`
  stays silent because the operation is awaited inside the scope.

### `ASYNC002`

- Bad: `try { return service.SaveAsync(); } finally { EndBusy(); }` emits
  `ASYNC002`.
- Good: `try { await service.SaveAsync(); } finally { EndBusy(); }` stays silent.

### `ASYNC010`

- Bad in WPF/ViewModel path: `LoadAsync().Result` emits `ASYNC010` as high
  severity.
- Less severe outside UI profile: `task.GetAwaiter().GetResult()` emits warning
  or info depending on configuration.

### `ASYNC020`

- Good: `private async void Button_Click(object sender, RoutedEventArgs e)` stays
  silent.
- Bad: `public async void Save()` emits `ASYNC020`.

### `ASYNC030`

- Bad: `_ = SaveAuditAsync();` emits `ASYNC030` unless the project config marks
  this helper shape as approved.
- Good: `FireAndForget.Run(() => SaveAuditAsync(), logger, "Save audit")` stays
  silent once the helper is configured.

### `ASYNC040`

- Info: a one-line `return await repo.GetAsync(id);` with no other evidence emits
  an info suggestion.
- Silent: any wrapper with validation, logging, `using`, `try/finally`, UI state,
  or context-sensitive evidence.

## Implementation order

1. Add the proposal, roadmap, and proposal-index entries.
2. Add hand-written OwnIR async fact fixtures and an `ownlang/async_rules.py`
   skeleton that emits `ASYNC001` from a `returned_task_escapes_using` hazard.
3. Add Roslyn extraction for `using`/`using var` plus direct returned invocation
   hazards.
4. Add `ASYNC002` for `try/finally` return-task hazards.
5. Add UI-sensitive blocking waits (`ASYNC010`) with WPF profile evidence.
6. Add `async void` and ignored task classification.
7. Add `ASYNC040` last, info-only, after the safety rules establish trust.

## Open questions

1. Does the OwnIR field name become `async_methods`, `async`, or a nested
   `methods[].async` block? Leaning: `async_methods` as a separate optional fact
   family, like `services` and `effects`.
2. How much layer classification belongs in Roslyn versus configuration? Leaning:
   Roslyn emits evidence (`inherits Window`, `implements INotifyPropertyChanged`,
   namespace/name hints); the core/profile decides severity.
3. What is the first approved fire-and-forget helper configuration surface? This
   likely belongs to P-015.
4. Should `ASYNC001` lower into the existing ownership flow engine eventually, or
   remain a direct async-rule finding? MVP can be direct; reuse is a later
   deepening opportunity.
5. Should `ValueTask` affine usage live here or under P-010 rich type disciplines?
   Leaning: P-010 owns `ValueTask` misuse; Own.Async may only emit basic shape
   facts if needed.

