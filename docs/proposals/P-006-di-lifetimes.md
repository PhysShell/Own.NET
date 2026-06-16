# P-006 — DI lifetime / captive dependency profile

- **Status:** in progress (P0 — clean lifetime model, little R&D, sells to
  ASP.NET). DI001 captive-dependency check built in the core (`ownlang/di.py`)
  over an OwnIR `services` registration graph, surfaced through the bridge with
  hand-written facts + tests. Next: the C# extractor that builds the registration
  graph from `services.Add{Singleton,Scoped,Transient}` + constructor injection
  (CI-only, like the rest of the extractor).
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
- **DI002 (warning):** a singleton captures a scoped dependency **weakly**
  (`WeakReference<Scoped>`). A weak reference fixes *retention* leaks, not a
  *lifetime contract* violation — the scoped service is still invalid outside its
  scope and may be disposed mid-use. Message: *"`WeakReference` does not make a
  scoped service safe to use outside its scope; resolve it inside a fresh scope
  via `IServiceScopeFactory`, or make the consumer scoped."*
- **DI003 (warning):** a transient `IDisposable` resolved from the **root**
  provider — never disposed until the app exits (a slow leak).

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
Startup.cs / Program.cs --[extractor: registrations + ctor graph]--> facts.json
     --[core: region ordering (OWN014 family)]--> DI001/DI002/DI003 @ registration site
```

Could be its own `Own.DI` profile sharing the lifetime core. Factory and
reflection registrations are recognised as "unknown lifetime" edges and excluded
rather than guessed.

## Open questions

1. Where to anchor the diagnostic — the registration line, the consuming
   constructor, or both? (Both, with the capture path shown, like OWN014's
   "expected: Window — actual: App — path: …".)
2. How far to chase transitive captures through the constructor graph before the
   dynamic cases make it unreliable? (Bounded depth; stop at unknown edges.)
3. Is `IServiceScopeFactory` usage inside a singleton recognised as the *fix*
   (so we stay silent), as it should be?
4. Treat transient-`IDisposable`-from-root (DI003) as warning or error? (Warning
   — it is a slow leak, not always a bug.)
