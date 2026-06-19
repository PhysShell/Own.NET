# Consolidation & positioning backlog

Working notes from an external architecture review (read-only pass over the repo:
README, ROADMAP, P-001/P-004/P-005/P-006, the OwnIR bridge and the Roslyn
extractor). The review's verdict and the cheap fixes are recorded here so the
deferred items do not evaporate; the cheap fixes were applied directly (see
below), the rest are **explicitly deferred** with rationale.

## Verdict (agreed)

The direction is right: **one core checker, Roslyn extracts facts only, OwnIR is
the seam, P0 is bug-driven (events / timers / `IDisposable` / DI / pool), and
lifetime regions reached `OWN014` through real C# facts.** The skeleton is sound.
The standing advice — **"strengthen the form, don't expand the dream"** — is taken.

One honest caveat about the review itself: it was a *read-only* pass (tests not
run), so it is weighted toward what you see **reading** (naming, file size,
schema) and blind to what you only see **running** (does Own.NET catch real bugs
others miss?). What is still unproven is **value**, not **form** — no rename or
file-split adds a single caught bug. So the highest-leverage next move is *not* on
this list: it is running the differentiation oracle on more real repos.

## Done now (this PR — cheap, doc-only, ~zero risk)

- **Doc drift fixed.** ROADMAP "frontend does NOT touch closures/interprocedural"
  now carves out the two honest exceptions that already exist: syntactic
  lambda-event-handler classification, and bounded *modular* interprocedural
  (contracts/inference) **in the core, not the frontend**.
- **Positioning sharpened.** ROADMAP framing now states plainly: Own.NET is one
  resource/lifetime analyzer **with profiles**, WPF is the *first* profile, the
  engine emits core `OWNxxx` codes + a `[resource: …]` kind tag (a dedicated
  `[profile: …]` label is itself one of the deferred items below).
- **Naming convention noted** in `docs/lifetimes.md`: `WPFxxx` are pattern-catalog
  IDs, not emitted codes.

## Deferred (recorded, NOT scheduled)

Ordered by the review; annotated with the real cost/benefit and the trigger that
should pull each off the shelf.

### 1. OwnIR v1 schema — rename `subscriptions` → `resources` (+ `captures`)
- **Why.** The component-level field is historically named `subscriptions` but
  holds any owned-resource record (subscription / timer / disposable / capture).
- **Reality check.** Milder than the review implies: `services` and `functions`
  are **already** separate top-level fields; only the component resource list is
  misnamed, and a `resource` kind discriminator already makes it work.
- **Cost.** Breaking `v0 → v1`: bridge + every fixture + the C# extractor + tests.
  Pure rename churn, **zero new caught bugs.**
- **Decision.** Do NOT do as a standalone churn PR. **Fold into the next PR that
  already touches the schema** (e.g. when a new resource kind needs first-class
  fields), with a transition window where the bridge reads both names.

### 2. Split the Roslyn extractor (`Program.cs`)
- **Why.** `OwnSharp.Extractor/Program.cs` carries input discovery, event/timer/
  disposable extraction, self-owned/handler/source-lifetime classifiers, lambda
  detection and IDisposable flow lowering in one file.
- **Cost.** Behaviour-preserving C# refactor; **but it is the frontend, which is
  CI-validated only (no local dotnet here), so it is the riskier kind to refactor
  blind, and it adds no caught bug.**
- **Decision.** Defer until it actually causes merge pain. Target split:
  `InputDiscovery` / `CompilationBuilder` / `OwnIrWriter`, `Extractors/*`,
  `Analysis/*`; first cut = peel `EventSubscriptionExtractor` +
  `SourceLifetimeClassifier` + `HandlerClassifier` out, keeping the
  `IDisposable` local-flow lowering separate from the subscription extractor.

### 3. Catalog rename `WPFxxx → SUB/TMR/DISP`
- **Why.** Positioning — `event +=` is `SUB001`, not `WPF001`.
- **Reality check.** Emitted codes are **already** core `OWN` + labels; `WPFxxx`
  live only in the docs/catalog. So this is doc churn, not an emitter change.
- **Decision.** Do it together with the OwnIR v1 / profile-config work, not alone.
  Keep genuinely WPF/XAML-specific patterns (ResourceDictionary / DataContext /
  Binding / WeakEventManager / visual-tree ownership) under a `WPF` profile label.

## Genuinely next *capabilities* (features, not refactors)

The review filed these under "next" but they are new capability, tracked where
features belong:

- **Transitive contract inference** — resolve the one ambiguous inference case
  (a param only *forwarded* to another call) from the callee's contract, fixpoint
  over the island's call-graph SCC. This is the real next brick: it would make the
  `forward → sink(consume)` shape catch the caller's double-dispose that v1
  deliberately leaves silent. (Follows P-006/2b.)
- **Lambda-handler tier** — finer subscription diagnostics for inline handlers
  (no unsubscribe handle; captures `this`/local state), tiered by source lifetime
  exactly like the existing static→`OWN014` / injected→`OWN001`-warning split.
- **DI registration extractor** — the C# frontend for `AddSingleton/Scoped/
  Transient` + constructor injection that feeds the already-built DI001 core
  (continues the lifetime story; sells to ASP.NET).

## The actual priority

Prove value, don't reshape form: run the oracle on more real OSS C# repos and
widen the differentiation set (where Own.NET catches what CodeQL / Infer# miss).
See `docs/notes/oracle.md` and `docs/notes/real-world-mining.md`.
