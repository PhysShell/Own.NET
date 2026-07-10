# DI001 end-to-end — the captive-dependency extractor (P-006)

The DI001 captive-dependency check has lived in the core (`ownlang/di.py`) for a
while, validated only on hand-written `services` facts. This slice gives it a
**C# front end**: the Roslyn extractor now builds the registration + constructor
graph from real code, so **DI001 fires end-to-end on C#** — no hand-authored
facts.

## The bug it catches

A **singleton** that depends on a **scoped** service captures that scoped instance
for the whole application lifetime — the classic ASP.NET Core *"Cannot consume
scoped service from singleton"* bug (a `DbContext` held by a singleton is the
canonical case: an open connection / request state promoted to process lifetime).
It is a deterministic property of the **registration graph**, which is exactly
OwnLang's lifetime ordering spelled in DI terms (`Transient ≲ Scoped < Singleton`).

The core rule (`di.py`, unchanged):

- `singleton -> scoped` — captive (the edge is the bug);
- `singleton -> transient -> scoped` — captive (a transient resolved by a
  singleton is itself singleton-lived, and drags the scoped along);
- `singleton -> singleton -> scoped` — **not** reported here (the inner singleton
  is the captor and is flagged on its own pass).

## What the extractor now reads

A purely **syntactic** pass over the same parsed trees (no SemanticModel needed —
in the spirit of the narrow frontend), in two steps:

1. **Constructor graph** — every class's widest **public** constructor's parameter
   types (the dependency edges), including a C# 12 **primary constructor**
   (`class Foo(Dep d)`, whose parameters live on the declaration, not a ctor
   member). DI's default provider resolves through public ctors only, so a wider
   non-public ctor's parameters are deliberately not counted (no false captive).
2. **Registrations** — every conventional `IServiceCollection` call:
   `AddSingleton` / `AddScoped` / `AddTransient`, in the generic
   `Add*<TService[, TImpl]>` form or the `Add*(typeof(TService)[, typeof(TImpl)])`
   form.

Each registration emits one `services` fact — the shape the core already consumes:

```json
{"name": "EmailSender", "lifetime": "singleton", "deps": ["AppDbContext"],
 "file": "DiCaptiveSample.cs", "line": 40}
```

`name` is the **service** type others inject (so an `AddScoped<IRepo, Repo>` keys
under `IRepo`, and a consumer injecting `IRepo` resolves to it); `deps` are the
**implementation**'s constructor parameter types; `file`/`line` anchor the finding
at the registration site.

### Non-goals stay silent, never guessed

Factory lambdas, reflection/assembly scanning, Scrutor, open generics and
config-driven wiring defeat a static graph. The extractor records what it *can*
read and treats the rest as an **unknown-dep node** (`deps: []`) — a node others
can still capture, but one that contributes no edges of its own. Per the P-006
non-goals: report the conventional shape, stay silent (not wrong) on the rest.

## Validation

- **Bridge-side, locally** — the `services` facts the extractor emits, fed through
  the real core, produce exactly the four expected DI001s (direct, transitive,
  interface, primary-ctor) and stay silent on the singleton→singleton edge and the
  public-ctor-only service. (No local .NET SDK, so the C#→facts step itself is
  validated in CI, like the rest of the frontend.)
- **End-to-end, in CI** — `frontend/roslyn/samples/DiCaptiveSample.cs` is wired
  into the `wpf-extractor` job. The assertions pin: a direct capture
  (`EmailSender -> AppDbContext`), a transitive one through a transient
  (`ReportService -> UnitOfWork -> AppDbContext`), an interface-registration one
  (`CacheService -> IRepo`), a C# 12 primary-constructor one
  (`PrimaryCtorService -> AppDbContext`), **exactly four** findings, and silence on
  `Metrics -> Clock` (singleton→singleton) and `PublicCtorOnly` (DI uses its public
  parameterless ctor; the wider private ctor's scoped dep is never resolved).

## Why it matters for differentiation

The captive dependency is an **ASP.NET-specific lifetime contract** that
general-purpose analyzers don't model — the same complementary story as the
subscription-leak class the cross-tool oracle already documented (CodeQL and
Infer# cover the Dispose/RAII family; neither flags these). It is also a clean
reuse win: a whole new diagnostic class on real C# with **zero core changes** —
the frontend just produces the `services` facts the lifetime core already checks.

## DI003 — transient `IDisposable` captured by a singleton (shipped)

A **transient `IDisposable` captured by a singleton** is resolved from the root (via the
singleton), promoted to the application lifetime, and disposed only when the root provider
is disposed — held far longer than its `transient` registration implies. Detected by the
same registration-graph DFS as DI001 (`ownlang/di.py` `find_captured_transient_disposables`,
target = *transient ∧ disposable*), surfaced as a **warning** (`severity="warning"` — a real
verdict shown soft; the framework allows it, the lifetime promotion is the smell). The
extractor marks a service `disposable` when its implementation's **own** base list names
`IDisposable`/`IAsyncDisposable` (syntactic — an inherited disposable is not guessed, so the
warning fires only where ownership is certain). Pinned end-to-end by `DiCaptiveSample.cs`
(`ConnectionWarmer` → transient `PooledConnection`) in the `wpf-extractor` CI job, and at the
graph level by `tests/test_ownir.py`.

## DI002 — scoped service captured *weakly* by a singleton (shipped)

A singleton that holds a **scoped** service via **`WeakReference<T>`** is the usual "fix"
for a DI001 captive — the weak reference stops the singleton pinning the scoped instance for
the GC. But it does **not** fix the *lifetime contract*: the scoped service is still resolved
from the root provider and lives for the application lifetime; the weak reference only hides
the GC-retention symptom (and the target may go dead under the consumer). *"Your fix isn't a
fix."* A **warning** (`severity="warning"` — real, shown soft), distinct from the strong
DI001 capture. The extractor reads a `WeakReference<X>` constructor parameter (`WeakRefInner`)
into a **separate `weak_deps`** list, deliberately kept **off** the DI001 strong graph, so the
same scoped service is either a strong captive (DI001) or a weak captive (DI002), never both;
`ownlang/di.py` `find_weak_captive_dependencies` flags a singleton that *reaches* a scoped
service from a weak dep — directly (`WeakReference<Scoped>`) or **transitively** through a
weakly-held transient that strongly drags in the scoped, the same strong-edge DFS DI001 runs
but rooted at the weak edge. Pinned end-to-end by `DiCaptiveSample.cs` — `WeakCache` /
`WeakCacheOpt` (`WeakReference<AppDbContext>`, the second nullable), and `WeakReport`
(`WeakReference<UnitOfWork>` → scoped `AppDbContext`, the transitive case); `WeakClockHolder →
WeakReference<Clock>` stays silent (a weak ref to a singleton is no mismatch) — in the
`wpf-extractor` CI job, and at the graph level by `tests/test_ownir.py`. It is a contract no
general-purpose analyzer models — even the developer's WeakReference "fix" is still flagged,
which is the key differentiation.

## DI004 — transient `IDisposable` service-located from the root provider (shipped)

The graph checks above (DI001/2/3) read the **registration graph** — who is registered with
which lifetime, and who they inject. DI004 reads what the graph cannot see: a **call site**. A
**singleton** that injects an `IServiceProvider` and resolves a **transient `IDisposable`** from
it *by hand* — `_provider.GetService<T>()` / `GetRequiredService<T>()`, the **service-locator
anti-pattern** — leaks. For a singleton the injected provider *is* the root container, and the
root tracks every `IDisposable` it resolves and disposes them only at application shutdown; so
each such call accumulates a transient that its `transient` registration says should be
short-lived (the well-known "transient disposables captured by the root container" leak), made
worse by being a *repeated runtime* resolution. A **warning**, like DI003 — the framework allows
it; the lifetime promotion is the smell.

It is filed as a **distinct code** (not "DI003, the explicit form"): the detection mechanism is
different (a resolution call site, not a constructor edge), the remediation is different (create
an `IServiceScope` and resolve from *its* provider), and one-code-per-rule keeps the SARIF
catalogue honest.

**The extractor** (still purely syntactic) records, per class, the names that refer to an
injected `IServiceProvider` — the constructor parameters of type `IServiceProvider` (usable
directly in a primary-ctor class), plus any **real class field** assigned one of them in a
constructor (block- **or** expression-bodied, `=> _sp = sp;`) or via a field initializer
(`IServiceProvider _sp = sp;`). It then records every `name.GetService<T>()` /
`GetRequiredService<T>()` whose **receiver is one of those names** into a separate
**`root_resolves`** list on the service fact. `ownlang/di.py` `find_explicit_root_resolutions`
flags a **singleton** whose `root_resolves` reaches a **transient ∧ disposable** service —
either the resolved type itself or one its transient subtree drags in: the same transient-edge
DFS DI003 runs, but entered at the service-location call site instead of a constructor edge (the
root builds the resolved type's whole transient subtree, so a non-disposable transient *wrapper*
still leaks the disposable transient it depends on).

**Precision (0 FP) is carried by guards**, each pinned by a silent control in
`DiCaptiveSample.cs`:

- **singleton-only** — only a *singleton*'s injected provider is the root container, so a
  singleton is what DI004 flags; the scoped `RequestResolver` is the silent control (a scoped
  service is resolved inside a request scope, whose provider disposes what it resolves).
- **the injected provider, never a scope's** — `scope.ServiceProvider.GetRequiredService<T>()`
  has a different receiver (a member access, not the injected name), so creating a scope and
  resolving from it — the *correct* pattern — stays silent (`ScopedResolver`).
- **a transient subtree, disposable, never scoped** — the root does not track non-disposables,
  and a *scoped* edge is not followed (resolving scoped from the root is DI001's concern / a
  runtime scope-validation error), so `PlainResolver` resolving the non-disposable `UnitOfWork`
  (whose only dep is scoped) stays silent.
- **real fields only** — the alias capture restricts assignment targets to declared class
  fields, so a constructor *local* alias never enters the provider-name set and cannot
  same-name-match an unrelated receiver (no false positive).

Aliases through locals, unknown receivers, and the non-generic `GetService(typeof(T))` form are
not guessed — they stay silent (recall left on the table to keep precision absolute). Pinned
end-to-end by `DiCaptiveSample.cs` — `ConnectionResolver` (block ctor), `ExprBodiedResolver`
(expression-bodied ctor), and the transitive `WrapperResolver → MidConnection → PooledConnection`
(primary-ctor field initializer), **exactly 3 DI004**, the three controls silent — in the
`wpf-extractor` CI job, and at the graph level by `tests/test_ownir.py`. No general-purpose
analyzer models this DI-container resolution contract.

## The consuming-constructor anchor (DI001/2/3, shipped)

A captive finding's primary anchor is the **registration site** — where you wire the
lifetime, and one place to fix it. But the capture is *introduced* somewhere else: the
**consuming constructor** that injects the captive dependency (P-006 open question #1, now
answered "both"). So each DI001/DI002/DI003 finding now also names that constructor —

- in the **message tail**: `… [consumed by the 'EmailSender' constructor at EmailSender.cs:25]`
  (visible on every surface — human, GitHub annotation, MSBuild, SARIF), and
- as a structured **SARIF `relatedLocation`** (a `Finding.related` triple), which GitHub code
  scanning renders as a second, clickable, labelled location — **cross-file** (the registration
  may live in `Startup.cs`, the ctor in `EmailSender.cs`).

The extractor records each implementation's ctor location — the widest **public** constructor's
declaration, or the class declaration for a C# 12 primary / implicit constructor — into
`ctor_file` / `ctor_line` on the service fact (`classCtorLoc`), plus the **implementation type**
that owns it in `ctor_type`. The core appends the anchor when the location is known and
**degrades cleanly** (no tail, no related location) when it is not, so hand-authored facts and an
older extractor still produce the registration-anchored form. The owner named is the *impl*, not
the service name: for an interface registration (`AddSingleton<IFoo, Foo>`) the captor's service
name is the ctor-less interface `IFoo`, but the consuming ctor is `Foo`'s — so the finding names
`Foo` (a Codex review catch). The finding is on the **singleton**, so the consuming constructor is
the singleton implementation's — the entry of the (possibly transitive) capture chain the path
already spells out. Pinned end-to-end by
`DiCaptiveSample.cs` (the explicit-ctor `EmailSender:25`, the primary-ctor `PrimaryCtorService:33`,
`ConnectionWarmer:50`, `WeakCache:57`) in the `wpf-extractor` CI job, the cross-file case by the
`tests/fixtures/ownir/di.facts.json` fixture, and the SARIF related location by `tests/test_ownir.py`.

**DI004's consumer is a call site, not a ctor** — and the leak *is* that call, so unlike
DI001/2/3 (a registration-graph property, anchored at the registration) the `GetService<T>()` /
`GetRequiredService<T>()` **resolution call site is DI004's PRIMARY anchor**, with the
registration demoted to the secondary (the `Finding.related` location + a `[singleton registered
at …]` message tail). The extractor emits, alongside `root_resolves`, a parallel
**`root_resolve_sites`** (`{type, file, line}` per resolved type — the call's location); the core
makes that the finding's `file`/`line` (Codex review: a `related`-only call site still annotates
`Startup.cs`, not the leak). The site is the **entry** type's call (`path[1]`): for a transitive
leak (`WrapperResolver → MidConnection → PooledConnection`) it points at where `MidConnection` was
hand-resolved, not at the container-built `PooledConnection`. Falls back to the registration site
when the call is unknown. Pinned by `DiCaptiveSample.cs` (`ConnectionResolver:79`,
`ExprBodiedResolver:123`, transitive `WrapperResolver:137`).

## DI005 — scope-resolved scoped service cached into a field (shipped), and the OQ#3 fix recognised

The remedy DI001/DI002 point at is **scope-per-operation**: inject `IServiceScopeFactory`, and per
operation `using var scope = factory.CreateScope();` then resolve the scoped dependency *inside* the
scope. DI005 catches that remedy done wrong — the scope-resolved **scoped** service **cached into a
field**. The field outlives the `using` scope, so the cached instance dangles after the scope (and
the service) is disposed *and* is promoted to the singleton's application lifetime: the captive is
back, hidden behind the API meant to fix it (a **warning**, anchored at the field-store site).

The extractor (still purely syntactic) records the **scope-creator** names with the same this-field
discipline as DI004 — a **directly-injected `IServiceScopeFactory`** *and* an injected
`IServiceProvider` (both expose `CreateScope()`) — then the scope locals their `CreateScope()`
produces, and every `scope.ServiceProvider.Get(Required)Service<T>()` whose result is **assigned to
a field** into a `scope_cached` list with its store site. `find_scope_cached_captives`
(`ownlang/di.py`) walks each cached entry's strong transient graph like DI001; the field-store site
is the finding's primary anchor, the registration the secondary.

**This is the answer to P-006 open question #3 — recognising the directly-injected
`IServiceScopeFactory` fix.** It needs no separate "approval" fact: the correct pattern (resolve
inside the scope, use, **discard** — a local, not a field store) simply **produces no `scope_cached`
entry**, so it is silent **by construction**. The "positive signal" is the *absence* of a captive
fact. Recognising the factory injection as licence to suppress *other* captive findings would be
wrong — a singleton that also injects a scoped service directly is still DI001. Pinned end-to-end by
`DiCaptiveSample.cs` (`ScopeCachingService` DI005 direct, `UnitOfWorkCachingService` DI005
transitive; `ScopeUsingService` — the correct scope-per-operation use — and `ClockCachingService`
— a cached *singleton*, shareable — both silent) in the `wpf-extractor` CI job, and at the graph
level by `tests/test_ownir.py`.

## Next (separate slices)
- Per-**parameter** precision for the captive anchor (the specific injecting parameter, not just
  the constructor).
- The plural `GetServices<T>()` and non-generic `GetService(typeof(T))` resolution forms (DI004
  currently reads the generic singular `Get(Required)Service<T>()`).
- **A scope-resolved scoped service that *escapes* its scope by being returned (or passed out as a
  `ref`/`out`/method argument)** rather than cached into a field — the same lifetime promotion as
  DI005, but through a data-flow edge the store-site pass does not model. Silent today
  (precision-safe: the extractor records only field stores, so an escaping local is no
  `scope_cached` fact). A candidate for a future flow-aware slice, not the store-site model.
