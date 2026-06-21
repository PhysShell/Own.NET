# P-006 — DI lifetime / captive dependency profile

- **Status:** in progress (P0 — clean lifetime model, little R&D, sells to
  ASP.NET). DI001 captive-dependency check built in the core (`ownlang/di.py`)
  over an OwnIR `services` registration graph, surfaced through the bridge. The
  C# extractor now **builds that graph from real code** — `services.Add{Singleton,
  Scoped,Transient}` (the generic `<TService[, TImpl]>` and `typeof(...)` forms)
  plus each implementation's constructor parameters — so **DI001 fires end-to-end
  on C#**, CI-validated on `frontend/roslyn/samples/DiCaptiveSample.cs` (direct,
  transitive-via-transient, and interface-registration captures flagged;
  singleton→singleton and clean registrations silent). See
  [docs/notes/di-captive-extractor.md](../notes/di-captive-extractor.md). **DI003**
  (a transient `IDisposable` captured by a singleton — promoted to application lifetime)
  and **DI002** (a scoped service held by a singleton via `WeakReference<T>` — still a
  captive: the weak ref hides the GC symptom, not the lifetime violation) now also fire
  end-to-end as **warnings**, CI-validated on the same sample. **DI004** (a transient
  `IDisposable` resolved by hand from a singleton's injected **root** `IServiceProvider` —
  `GetService<T>()` / `GetRequiredService<T>()`, the service-locator anti-pattern) extends
  the family to a **call site** the registration graph cannot see, also a CI-validated
  warning on the same sample.
- **Depends on:** `spec/Lifetimes.md` (the region-ordering model behind OWN014),
  [P-001](P-001-csharp-extractor.md) (the C# seam). See
  [`docs/ROADMAP.md`](../ROADMAP.md) (Milestone 3).

## Motivation

The captive dependency is one of the most common — and most quietly damaging —
.NET DI bugs: a `Singleton` takes a `Scoped` (or transient `IDisposable`)
dependency in its constructor, and that shorter-lived service is effectively
promoted to live as long as the app — an open DB connection held for the process
lifetime, request-specific state shared across requests, leaks. Microsoft calls
it a misconfiguration; it is **exactly** OwnLang's lifetime ordering, just spelled
in DI terms:

```text
Transient ≲ Scoped < Singleton            (Request < App)
forbid: store Scoped into Singleton       (a longer-lived owner retains a shorter-lived value)
```

This is almost a free win: the lifetime machinery behind OWN014 (a value escaping
to a longer-lived region) already models it.

## Scope

- **DI001 (error):** a singleton service captures a scoped dependency (directly,
  or transitively through the constructor graph).
- **DI002 (warning) — shipped:** a singleton captures a scoped dependency **weakly**
  (`WeakReference<Scoped>`). A weak reference fixes *retention* leaks, not a
  *lifetime contract* violation — the scoped service is still root-resolved, lives
  for the app lifetime, and may be disposed mid-use. The `WeakReference<X>` ctor
  parameter is read into a separate `weak_deps` list (off the DI001 strong graph), and
  `find_weak_captive_dependencies` flags a singleton whose `weak_deps` names a scoped
  service. CI-validated on `DiCaptiveSample.cs` (`WeakCache`).
- **DI003 (warning) — shipped:** a transient `IDisposable` **captured by a singleton**
  is resolved from the root (via the singleton), promoted to application lifetime, and
  disposed only at root disposal — held far longer than its `transient` registration
  implies. The same registration-graph DFS as DI001 (target = transient ∧ disposable);
  the extractor marks a service `disposable` from its impl's own `: IDisposable` base.
- **DI004 (warning) — shipped:** the **explicit / service-locator** form of the
  transient-`IDisposable` leak — a singleton that resolves it **by hand** from its injected
  **root** `IServiceProvider` (`GetService<T>()` / `GetRequiredService<T>()`), which the
  registration graph cannot see (it is a resolution call site, not a constructor edge). The
  extractor records the injected-provider names per class (ctor params of type
  `IServiceProvider` plus the real class fields assigned from them — in a block- or
  expression-bodied ctor, or a field initializer) and reads each resolution off them into a
  `root_resolves` list; `find_explicit_root_resolutions` walks the resolved type's transient
  subtree exactly as DI003 does (so a non-disposable transient *wrapper* that drags in a
  transient `IDisposable` is caught too) and flags the singleton. Filed as a **distinct code**
  (not "DI003 explicit"): different detection, different fix (resolve from an `IServiceScope`).
  Precision is held by guards — singleton-only, the injected provider (never a scope's
  `.ServiceProvider`), transient ∧ disposable (scoped edges not followed), and alias capture
  restricted to real fields (no local-alias false match) — each pinned by a control on
  `DiCaptiveSample.cs` (`ConnectionResolver` / `ExprBodiedResolver` / transitive `WrapperResolver`
  flagged; `ScopedResolver` / `PlainResolver` / `RequestResolver` silent).

Suggested fix attached to DI001/DI002: inject `IServiceScopeFactory`, and per
operation `using var scope = factory.CreateScope();` then resolve the scoped
dependency inside the scope (the standard `BackgroundService`/singleton remedy).

## Non-goals

- A general aliasing/escape analysis of arbitrary object graphs — this is the
  *registration + constructor* graph only.
- Resolving the hard dynamic cases: factory registrations, `IServiceProvider.
  GetRequiredService` inside a lambda, open generics, conditional registration,
  reflection scanning, Scrutor, config-driven wiring. These defeat a static
  graph; report only the *conventional* `IServiceCollection` shape and stay
  silent (not wrong) on the rest. (The brainstorm's "100% static" claim is
  optimistic — conventional registrations are reliably catchable; dynamic ones
  are not.)
- DI001 is **not** "solved by `WeakReference`" — see DI002; the right fix is a
  scope boundary or a lifetime redesign, not a weaker reference.

## Sketch

Two facts feed the existing lifetime checker: a **registration graph** (service →
lifetime, from `AddSingleton`/`AddScoped`/`AddTransient`) and a **constructor
dependency graph** (service → its ctor parameter types, from Roslyn). The core
then checks the same region ordering it already uses for OWN014: a longer-lived
region (Singleton) must not retain a value from a shorter-lived region (Scoped).

```text
Startup.cs / Program.cs --[extractor: registrations + ctor graph + resolution call sites]--> facts.json
     --[core: region ordering (OWN014 family)]--> DI001/DI002/DI003/DI004 @ registration site
```

Could be its own `Own.DI` profile sharing the lifetime core. Factory and
reflection registrations are recognised as "unknown lifetime" edges and excluded
rather than guessed.

## Open questions

1. Where to anchor the diagnostic — the registration line, the consuming
   constructor, or both? **Resolved: both**, with the capture path shown, like OWN014's
   "expected: Window — actual: App — path: …".
   For the captive family (DI001/DI002/DI003) the finding keeps its **primary** anchor at
   the registration site and names the **consuming constructor** — where the captive is
   injected — both in the message tail
   (`[consumed by the '<impl>' constructor at <file>:<line>]`) and as a structured
   **SARIF `relatedLocation`** (clickable, cross-file). The owner named is the
   **implementation** type that owns the ctor (for an interface registration that is the
   impl, not the ctor-less service interface). The extractor records each implementation's
   ctor location (the widest public ctor, or the class declaration for a primary/implicit
   ctor); the core appends it when known and degrades cleanly when not.
   **DI004** is also anchored, but the *other* way round: its consumer is a **resolution call site**
   (`GetRequiredService<T>()`), and the leak *is* that call — so the call site is DI004's **primary**
   anchor (extractor threads each call's location through a parallel `root_resolve_sites` fact; the
   finding lands at the *entry* type's call, even for a transitive leak), with the registration
   demoted to the secondary. Registration-graph rules anchor at the registration; the call-site rule
   anchors at the call.
2. How far to chase transitive captures through the constructor graph before the
   dynamic cases make it unreliable? (Bounded depth; stop at unknown edges.)
3. Is `IServiceScopeFactory` usage inside a singleton recognised as the *fix*
   (so we stay silent), as it should be? (For the explicit form (DI004): **yes**, by
   construction — DI004 records only `GetService<T>()` / `GetRequiredService<T>()` on the
   injected `IServiceProvider` names and **excludes** a scope's `.ServiceProvider` receiver, so
   resolving from a scope created with `CreateScope()` is silent. Modelling a directly-injected
   `IServiceScopeFactory` is not yet implemented — a natural future extension.)
4. Treat transient-`IDisposable`-from-root (DI003/DI004) as warning or error? (Warning
   — it is a slow leak, not always a bug. DI004's call-site form is repeated at runtime,
   arguably worse, but kept a warning for consistency with DI003.)
