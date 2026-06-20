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

1. **Constructor graph** — every class's widest constructor's parameter types
   (the dependency edges).
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
  the real core, produce exactly the three expected DI001s (direct, transitive,
  interface) and stay silent on the singleton→singleton edge. (No local .NET SDK,
  so the C#→facts step itself is validated in CI, like the rest of the frontend.)
- **End-to-end, in CI** — `frontend/roslyn/samples/DiCaptiveSample.cs` is wired
  into the `wpf-extractor` job. The assertions pin: a direct capture
  (`EmailSender -> AppDbContext`), a transitive one through a transient
  (`ReportService -> UnitOfWork -> AppDbContext`), an interface-registration one
  (`CacheService -> IRepo`), **exactly three** findings, and silence on
  `Metrics -> Clock` (singleton→singleton) and the clean leaves.

## Why it matters for differentiation

The captive dependency is an **ASP.NET-specific lifetime contract** that
general-purpose analyzers don't model — the same complementary story as the
subscription-leak class the cross-tool oracle already documented (CodeQL and
Infer# cover the Dispose/RAII family; neither flags these). It is also a clean
reuse win: a whole new diagnostic class on real C# with **zero core changes** —
the frontend just produces the `services` facts the lifetime core already checks.

## Next (separate slices)

- **DI002** — a singleton capturing a scoped dependency *weakly*
  (`WeakReference<Scoped>`): a warning, since a weak reference fixes retention but
  not the lifetime-contract violation.
- **DI003** — a transient `IDisposable` resolved from the **root** provider, never
  disposed until the app exits (a slow leak).
- Anchoring the finding at the **consuming constructor** as well as the
  registration site (P-006 open question #1), with the capture path shown.
