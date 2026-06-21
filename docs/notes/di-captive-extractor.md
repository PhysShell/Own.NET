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
directly in a primary-ctor class) plus any field assigned one of them — then every
`name.GetService<T>()` / `GetRequiredService<T>()` whose **receiver is one of those names** into a
separate **`root_resolves`** list on the service fact. `ownlang/di.py`
`find_explicit_root_resolutions` flags a **singleton** whose `root_resolves` reaches a service
that is **transient ∧ disposable**.

**Precision (0 FP) is carried by three guards**, each pinned by a silent control in
`DiCaptiveSample.cs`:

- **singleton-only** — a *scoped*/transient service's injected provider is its **request scope**
  (which disposes what it resolves), not the root, so it is never flagged (`RequestResolver`,
  scoped, stays silent).
- **the injected provider, never a scope's** — `scope.ServiceProvider.GetRequiredService<T>()`
  has a different receiver (a member access, not the injected name), so creating a scope and
  resolving from it — the *correct* pattern — stays silent (`ScopedResolver`).
- **transient ∧ disposable** — the root does not track non-disposables, so a non-disposable
  transient resolved from the root does not leak and is left silent (`PlainResolver` resolving
  the non-disposable `UnitOfWork`).

Aliases through locals, unknown receivers, and the non-generic `GetService(Type)` form are not
guessed — they stay silent (recall left on the table to keep precision absolute). Pinned
end-to-end by `DiCaptiveSample.cs` (`ConnectionResolver` → transient `IDisposable`
`PooledConnection`, **exactly 1 DI004**, the three controls silent) in the `wpf-extractor` CI
job, and at the graph level by `tests/test_ownir.py`. No general-purpose analyzer models this
DI-container resolution contract.

## Next (separate slices)
- Anchoring the finding at the **consuming constructor** (DI001/2/3) or the **resolution call
  site** (DI004) as well as the registration site (P-006 open question #1), with the path shown.
- The plural `GetServices<T>()` and non-generic `GetService(typeof(T))` resolution forms (DI004
  currently reads only the generic singular `Get(Required)Service<T>()`).
