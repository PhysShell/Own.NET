# Singleton captures a scoped DbContext (DI001)

**Pattern:** the canonical ASP.NET Core *captive dependency*. A service registered
`AddSingleton` takes a `AddScoped` service (here an EF Core `AppDbContext`) in its
constructor. The container builds **one** scoped instance with the singleton and
holds it for the whole application lifetime — a DB connection pinned for the
process, request-specific state shared across requests, and a `DbContext` used
concurrently from multiple threads (it is not thread-safe). Microsoft surfaces it
at startup as *"Cannot consume scoped service 'AppDbContext' from singleton
'NotificationService'."*

**Why it is exactly OwnLang's lifetime model.** A captive dependency *is* the
OWN014 region-escape rule in DI clothing: `Scoped < Singleton` (request < app), and
storing a shorter-lived value into a longer-lived owner is the violation. The core
runs the same lifetime ordering it uses for OWN014; `ownlang/di.py`
(`find_captive_dependencies`) walks the registration + constructor graph and flags
the capture **at the registration site**, naming the consuming constructor.

**The fix (after.cs).** Inject `IServiceScopeFactory` (a singleton) instead of the
scoped service, and open a fresh scope per operation
(`using var scope = _scopes.CreateScope();`), resolving the `DbContext` inside it.
The singleton's constructor no longer depends on a scoped service, so the captive
edge is gone (DI001 silent), and the resolve is off the scope's provider rather than
an injected root `IServiceProvider`, so the service-locator rule (DI004) is silent
too.

**Honesty / scope.** This is the DI family's first **real-world** corpus case; the
captive classifier was previously pinned only on the synthetic
`frontend/roslyn/samples/DiCaptiveSample.cs`. There is **no `case.own`**: the `.own`
DSL has no service-registration surface (DI lives in the `services` fact graph, not
the resource/flow language), so the captive cannot be hand-reduced to `.own` the way
an ownership bug can — `corpus/di/` is therefore scanned by the **dotnet
`corpus-benchmark` job only** (extractor → `services` graph → DI001), not the
Python `test_corpus` `.own` runner. `before.cs` / `after.cs` are representative of
the pattern, not a verbatim diff. The transitive, interface-registration, weak
(`DI002`), transient-`IDisposable` (`DI003`), and service-locator (`DI004`) variants
remain pinned on the synthetic sample.

Reference: [P-006](../../../docs/proposals/P-006-di-lifetimes.md); Microsoft "DI
guidelines — scoped service as singleton" (the captive-dependency anti-pattern).
