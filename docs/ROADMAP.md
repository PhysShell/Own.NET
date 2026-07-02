# Own.NET — roadmap & idea backlog

The strategy hub. `spec/` is normative (what is true today, pinned by tests);
`docs/proposals/` are exploratory designs; **this file** is the map over them:
priorities, milestones, the framing, the design philosophy, and — most importantly
— a place where every idea raised in design discussion is *written down so it does
not evaporate*. An idea here is "on the record for consideration", not a
commitment. When an idea earns a design, it becomes a `P-NNN` proposal; when a
proposal ships, its behaviour moves into `spec/`.

## The framing (the one-sentence pitch)

The first public pitch is **not** "we're building a borrow checker for C#". It is:

> **Own.NET finds lifetime/resource bugs that C# cannot express:** WPF/event
> leaks, missing `Dispose`, DI lifetime mismatch, and pooled-buffer misuse.

That is concrete, painful, and shippable without a five-year R&D detour. The
borrow checker is the *first combat module*, not the whole universe.

Read structurally, Own.NET is **one resource/lifetime analyzer with profiles** —
subscriptions, timers, `IDisposable`, DI lifetimes, pooled buffers — and **WPF is
the first configured profile, not the identity.** The engine emits domain-neutral
core verdicts (`OWN001/002/003/014`) plus a `[resource: …]` kind tag; a profile only
contributes the lifetime facts (WPF's `ViewModel < Window < App`, `Loaded`/`Closed`
= release regions). (A dedicated `[profile: …]` label is **not** emitted today — it
is a consolidation-backlog item.)
Code names that still read `WPFxxx` are pattern-catalog IDs, not emitted codes — the
catalog rename (`SUB`/`TMR`/`DISP`) and the other consolidation items are recorded in
[docs/notes/consolidation-and-positioning.md](notes/consolidation-and-positioning.md).

The long-term identity the backlog is aiming at:

> **An external static-contract layer for C#/.NET** that adds ownership,
> typestate, effects, capabilities, and domain-specific types **without
> rewriting the codebase.**

### Positioning against the competition (not another SAST)

The competition is already standing around this field with shovels and enterprise
sales badges. CodeQL (semantic queries / code scanning), Sonar (quality / bugs /
smells), Semgrep (rule-based AppSec), Snyk Code (SAST), and the AI PR reviewers all
sell the **broad** promise: *"we'll find vulnerabilities / bugs / smells."* Entering
that arena as *"another static analyzer / AI code reviewer / SAST"* is a fight lost
to marketing budget, not to merit.

So Own.NET must **not** be pitched as any of those. The narrower, defensible niche:

> a **cross-language resource / lifetime / effect contract checker** — who holds
> whom, who must release, which resource outlives which, which effect can
> runaway, where a lifecycle contract is broken.

That is a different promise from *"an AI reviewer said this looks suspicious."* And
it is deterministic where the AI reviewers are not — the grown-up framing is *an
LLM may **propose** a suspicious lifecycle contract; Own **verifies** it
deterministically* (reproducible rule, SARIF, suppression/spec, cross-language
model). Not a head-on fight with AI review — a layer underneath it.

### From memory leaks to effect storms (one model, many skins)

The "big idea" that makes the niche coherent: four bugs that look unrelated are the
**same lifecycle/resource-contract failure** in different ecosystems —

| Bug | The contract that broke |
|-----|-------------------------|
| WPF event leak | a long-lived publisher keeps a `ViewModel` alive |
| DI captive dependency | a long-lived service retains a scoped service |
| ArrayPool view-after-return | released backing storage still has a borrowed view |
| **React effect storm** | an unstable dependency repeatedly re-triggers a network effect |

One model (source lifetime / resource / effect / cleanup / stability), one IR
(OwnIR facts), one checker (the `ownlang/` core). The React row is the
Cloudflare-shaped hook — used **honestly**: *"not all lifecycle bugs leak memory;
some leak requests,"* never *"we'd have prevented the Cloudflare outage."* Its
design is [P-020](proposals/P-020-ownts-react-effects.md) (the `Own.React` effect
profile under the OwnTS frontend, [P-017](proposals/P-017-multi-stack-frontends.md)).

## Design philosophy (the load-bearing constraints)

- **One checker.** The Python core in `ownlang/` is the single source of truth.
  Every frontend (the `.own` DSL, the Roslyn C# extractor of P-001, anything
  later) *produces or consumes OwnIR facts* in the spec's vocabulary. A second
  checker would drift — the project's own meta-irony.
- **Bug-driven expansion.** Do not support a C#/.NET feature because the platform
  has it. Support it because a *real bug* needs it. "We supported 40% of the
  language and found zero bugs" is the failure mode we are avoiding.
  - Concretely: prove Own.NET finds **one** real memory/resource bug in real C#,
    then widen the frontend to fit exactly the next real bug.
- **Narrow C# frontend, intraprocedural first.** The frontend's job is not to
  "understand C#" — it uses a project-local `SemanticModel` only for binding and
  type resolution (is a `+=` LHS an event or a number? — [P-014](proposals/P-014-semantic-resolution.md)),
  not for whole-language understanding (async, generics, LINQ, closures, pattern
  matching, overload resolution, nullable flow, source generators stay out of
  scope). Its job is to extract *facts*: acquire / borrow / use / release / escape
  / control-flow.
- **Refuse the soul-eating version.** Every proposal's Non-goals section is the
  most important one. Boredom keeps projects alive.

### What the C# frontend deliberately does NOT touch yet

`async`/`await`, full generics, LINQ, general closure/dataflow analysis, virtual
dispatch, whole-program analysis, source generators, `unsafe` pointer arithmetic,
the XAML/binding engine. Not "never" — just not *before* the tool has found its
first real bug. An `async` method in v0 is honestly skipped (or flagged
"unsupported"), because honestly skipping beats confidently lying; the market for
confident-but-wrong tooling is already saturated.

Two honest exceptions have since been carved out, because a real bug needed each:

- **Syntactic lambda-event-handler classification.** General closure analysis stays
  out, but the frontend *does* recognise an inline `evt += (s,a) => …` handler — an
  inline handler caches no delegate, so it can never be `-=`'d, which is part of the
  subscription-leak profile. It is the syntactic *shape*, not dataflow over captures.
- **Bounded, *modular* interprocedural — in the core, not the frontend.** The
  frontend still extracts facts one method at a time. But the core now checks
  ownership *across* methods **compositionally, against a callee's contract**
  (`consume`/`borrow`, inferred from its body when unannotated) — the signature is
  the cut point, never whole-program points-to (P-006/2b). "Interprocedural" in the
  exclusion above means the intractable *whole-program* kind, which stays out.

## Priorities

Targets are ranked by four criteria: (1) the pain is frequent or expensive,
(2) it is at least partly catchable *statically*, (3) it maps cleanly onto
ownership/lifetime/effects, (4) an MVP needs no PhD in Roslyn.

| Tier | Targets | Proposal |
|------|---------|----------|
| **P0** | WPF/event/timer/subscription leaks; `IDisposable` ownership (leaks, fields, use-after-dispose); DI lifetime mismatch (captive dependency) | [P-004](proposals/P-004-wpf-lifetime-profile.md), [P-005](proposals/P-005-idisposable-ownership.md), [P-006](proposals/P-006-di-lifetimes.md) |
| **P1** | ArrayPool/Span ownership-view bugs; hidden effects / architecture rules | [P-007](proposals/P-007-arraypool-span.md), [P-008](proposals/P-008-effects-and-resources.md) |
| **P2** | async resource lifecycle / WPF async audit; `ValueTask` affine usage; typestate/protocols | [P-021](proposals/P-021-async-audit-pack.md), [P-008](proposals/P-008-effects-and-resources.md), [P-010](proposals/P-010-type-disciplines.md) |
| **P3** | LOH fragmentation; static-collection memory bloat; cross-thread `ObjectDisposedException` | — (runtime-bound; see detectability matrix) |

> **Are we showable yet?** The concrete "delicious .NET alpha" gate — the A–G bar
> (`dotnet tool` / Action / SARIF / 5 diagnostics / bad-ok examples / case studies /
> suppression policy), the honest current status against it, and the 80/20 rule —
> lives in [docs/notes/alpha-readiness.md](notes/alpha-readiness.md). Short version:
> capability is past alpha; the gap to "people install it" is *packaging* (a single
> `ownsharp check MyApp.sln` CLI, a wedge landing README, packaged case studies).

**The five concrete diagnostics to build first** (balanced across real pain,
architectural strictness, and the borrow-checker showcase):

1. `WPF001` — event/subscription `+=` without `-=` (the WPF spike; P-001 v0 ✅)
2. `WPF002` — `DispatcherTimer`/`Timer` `Tick`/`Elapsed` without stop/detach ✅
3. `OWN001` — `IDisposable` field the class `new`s but never disposes ✅
4. `DI001` — singleton captures a scoped dependency ✅ (core check + C#
   registration-graph extractor built; end-to-end on real C#)
5. `POOL001` — `ArrayPool` buffer `Rent`ed but never `Return`ed ✅
   (`POOL002` `Span`/view used after `Return` ✅; `POOL003` double-return,
   `POOL005` full-length over-read built too — see P-007)

### Milestones

1. **WPF leak spike** — find 1–3 real subscription/timer leaks in real code (P-004).
   ✔ *Done* — mining real OSS C# surfaced real leaks in `NickeManarin/ScreenToGif`:
   a view→view-model subscription (`VideoSource`) and two `SystemEvents` leaks, plus
   precise/clean results on disciplined code. The WPF reference unlock
   (`OWN_EXTRA_REF_DIRS`) and the self-owned-control precision gap it revealed are
   both closed — the exemption now covers `ref`/`out`-built fields (via the class's
   own helper) and template
   parts, cutting ScreenToGif's WPF-profile findings 123 → 36 (real leaks intact).
   The cross-tool oracle confirms the differentiation: CodeQL *and* Infer# (the latter
   via a buildable fixture) cover the Dispose/RAII class and flag none of these
   subscription leaks — agreeing with Own.NET only on a Dispose leak, never a subscription.
   The oracle also drove down the *other*-class recall gap (Dispose leaks Own.NET missed
   because the flow detector skipped methods with unmodelled constructs): `for` and `try`
   are now lowered — sequentially, then with an **exception-edge** model that injects a
   throw exit before each may-throw leaf in a `try` (including inside nested branches, with a
   constructor `new` as a throw point and typed/filtered catches handled). That closes the
   `dispose-not-called-on-throw` shape, which now lands in cross-tool **Agree** with
   CodeQL's dedicated query on the fixture. `finally`-before-`return`, `do` and `switch` are
   lowered too, so the flow detector covers every common control-flow construct (only
   `goto`/labeled statements and a few exotic forms still bail). See
   [docs/notes/real-world-mining.md](notes/real-world-mining.md).
2. **Resource core** — generalise WPF subscriptions + `IDisposable` into one
   acquire/release/owner/release-region model (P-004 ∪ P-005), so WPF is a
   *profile*, not a one-off.
   ◑ *In progress* — the acquire/release half is the live engine (OWN001 across
   subscriptions / timers / fields / pools). The **region half is now wired end to
   end through the C# extractor**: a static-source `+=` is lowered to a *tokenless*
   `capture` OwnIR fact that routes through the lifetime/region engine and surfaces
   as **OWN014** (the WPF "escape to App"), so the subscription leak is expressible
   through the *general* owner/release-region model — not a bespoke detector. It is
   also more *precise* than the token model: a source that does not provably outlive
   the subscriber stays silent (no false positive) where the token tier only warns,
   and a released `-=` mitigates the capture. Proven by the `capture` fixture, the
   `StaticEventEscapeViewModel` sample (CI `wpf-extractor` → OWN014), and the
   `corpus/wpf/systemevents-region-escape` reduction (P-004 WPF005 ✅). The
   **injected-source tier migration is now shipped** via the DI graph (P-006 + P-004,
   `di_source_life`): an injected `+=` whose `source_type` resolves in the registration
   graph reroutes through the region engine — a source proven to strictly **outlive** the
   subscriber escalates the OWN001 *warning* to **OWN014** (a proven captive/region escape,
   error-tier), a source **co-lifetimed or shorter** is *refuted* and dropped silently, and
   an **unresolved** source (not in the DI graph) correctly stays the honest OWN001 warning
   ("may outlive"). Covered by `test_ownir.py` (208/208 bridge checks, incl. the DI-sourced
   escape + the "no DI info → stays a warning" regression). Residual is by design, not a gap:
   a non-DI injected source has no provable lifetime, so warning is the honest verdict.
   Escalating *those* by a curated "known app-lived source type" allowlist (e.g. MVVM
   `IMessenger`/`IEventAggregator`) is **deliberately deferred as FP-prone** — modern
   CommunityToolkit `WeakReferenceMessenger` holds recipients *weakly* (no leak), so a
   type-name allowlist would mis-flag the safe case; it needs weak-vs-strong reference
   evidence we don't model.
3. **DI lifetimes** — registration + constructor graph; captive dependency (P-006).
   ◑ *In progress* — DI001 lands end to end: the C# extractor builds the
   registration + constructor graph from `Add{Singleton,Scoped,Transient}` (generic
   and `typeof(...)` forms) and the core flags the captive — direct, transitive
   through a transient, or through an interface registration — CI-validated on
   `DiCaptiveSample.cs`. The whole captive family is now built end to end on the same
   sample: **DI002** (a scoped service held weakly via `WeakReference<T>` — still
   root-resolved/app-lived), **DI003** (a transient `IDisposable` captured by a singleton),
   and **DI004** (the service-locator form — a transient `IDisposable` resolved by hand from
   a singleton's injected **root** `IServiceProvider` via `GetService`/`GetRequiredService`),
   all warnings; plus the **consuming-constructor anchor** (a captive names both its
   registration site and the ctor that injects it, as message tail + SARIF relatedLocation).
   **DI005** (the fix done wrong — a singleton that injects `IServiceScopeFactory`, opens a
   scope, but **caches** the scope-resolved **scoped** service into a field, so it dangles after
   the scope is disposed and is promoted to app lifetime) is built end to end too, a store-site
   property anchored at the field assignment. The family now also has its first **real-world
   corpus case** — a singleton injecting a scoped EF `DbContext` → DI001 (`corpus/di/`, a
   benchmark-only corpus since DI has no `.own` form). Remaining (deliberate-deferral / future):
   directly-injected `IServiceScopeFactory`-as-a-positive-signal recognition (P-006 OQ#3), and
   the dynamic registrations that are explicit non-goals.
4. **Pool/Span** — `Rent`/`Return`, borrowed views, return-invalidates-views,
   known-bug replay corpus (P-007). The borrow checker on stage at full height.
   ◑ *In progress* — POOL001 (leak), POOL002 (view-after-return → OWN002),
   POOL003 (double-return/dispose, ArrayPool *and* MemoryPool) built end to end;
   POOL004 (view escape) and POOL005 (full-length over-read, local **and** pooled
   `byte[]` FIELD) first slices built. Remaining: a POOL005 view stored INTO another
   field, deeper POOL004 escape, and the real-world replay targets (dotnet/runtime,
   Nethermind, AiDotNet.Tensors).
5. **Effects** — `pure` / `use !Db` / `use !Log` / `use Clock`, layer policies
   (P-008). The architectural X-ray — landed *after* the leak checkers prove value.
6. **Platform-agnostic core (multi-stack)** — *horizon, on the record for
   consideration only.* The same OwnIR seam, reused for non-.NET stacks to prove the
   "one core, frontends only extract facts" spine was not .NET-shaped luck (P-017).
   Decision recorded: **JS/TS = one frontend family (`OwnTS`), two confidence tiers**
   (TS type-aware via the TypeScript Compiler API; JS best-effort via syntax/JSDoc) —
   *not* two products; **Java/Kotlin = split frontends** (`OwnJava` via Error Prone/
   JDT/Spoon, `OwnKotlin` via Detekt/KSP/K2) **unified by one `OwnJVM` profile** —
   because the JVM lifecycle/resource model is shared but the source tooling is not.
   The axis the naive layout conflates is **language frontend** (`OwnTS`/`OwnJava`/
   `OwnKotlin`) vs **platform profile** (`OwnReact`/`OwnJVM`/`OwnAndroid`/`OwnSpring`)
   vs **core** — a brand-per-framework layout "is not a product line, it is a census."
   Gated behind a tasty .NET alpha + a real cross-stack bug; the first slices are a
   `useEffect`-cleanup *marketing* spike and a listener-leak *research* spike, each
   `acquire` without `release` → the existing `OWN001`. See
   [P-017](proposals/P-017-multi-stack-frontends.md).

## What static analysis can and cannot catch (the reality matrix)

A checker scope must respect this. The corpus (P-012) tags every case by which
bucket it falls in, so we never promise a runtime-only bug to a static checker.

| Bug class | Static (Roslyn) | Why |
|-----------|-----------------|-----|
| Captive dependency (singleton→scoped) | ✅ deterministic | visible in the type/registration graph |
| Missing `Dispose` (local / field) | ✅ deterministic | a missing call is structurally visible |
| `ArrayPool.Rent` without `Return` (one method) | ✅ deterministic | both calls in one CFG |
| Simple use-after-dispose (one method) | ✅ deterministic | `x.Dispose(); x.Use();` is visible |
| `event +=` without `-=` | ⚠️ heuristic | depends on object lifetime → warn only in long-lived owners; false positives |
| Ownership transfer through a callee | ⚠️ heuristic | `ProcessStream(s)` may dispose internally |
| Cross-thread `ObjectDisposedException` | ❌ impossible | a happens-before race, not a structure |
| LOH fragmentation | ❌ impossible | depends on runtime data volume / GC timing |
| Static-collection memory bloat | ❌ impossible | depends on business data, not code shape |
| Unmanaged cyclic refs / `AllocHGlobal` freed on all paths | ❌ ~impossible | needs whole-program flow we don't have |

Static analysis is the first line of defence (it stops the dumb bugs early); real
production leaks still need profilers (dotMemory, PerfView) and dump analysis.
Say so honestly in any talk/README.

## Why not a full Rust-style borrow checker for C#

Worth stating because people ask. It is not (mainly) reimplementable wholesale,
for three structural reasons:

1. **GC philosophy conflict.** C# was designed so the programmer need not think
   about memory. A full ownership/lifetime regime would make the GC redundant —
   and turn everyday C# into a fight with the checker (lifetimes on nearly every
   variable). Own.NET instead checks *narrow regions and explicit resources*,
   leaving the GC to do the rest.
2. **`IDisposable` is a pattern, not a language rule.** To the C# compiler,
   `.Dispose()` is just a method; the object is still valid afterwards. Making
   `Dispose()` "kill" a variable at the type level would change the language
   semantics and break billions of lines. Own.NET supplies that *typestate*
   externally instead (P-005, P-010).
3. **Dynamism.** Objects live on the heap, reachable from many places; DI
   containers and reflection build dependency graphs the compiler cannot trace.
   Ownership analysis is happiest where the dependency tree is clear, which is why
   the frontend stays narrow and fact-based.

Note the platform is already moving this way — `Span<T>`, `Memory<T>`, `ref
struct` are "Rust strictness, C# ergonomics", compiler-checked escape rules.
Own.NET is complementary: the contracts the compiler still cannot express.

## A note on "top .NET errors" statistics

There is no good *public* dataset of real .NET production crashes — it lives in
private dashboards. Any prioritisation numbers in these proposals are **proxy /
hypothesis estimates**, drawn from analyzer rules, exception docs, DI guidance and
issue-tracker keyword frequency — *not* measured statistics. The job of the
mining pipeline (P-012) is to *replace* those guesses with real counts from our
own scan. Label them as estimates wherever they appear.

## Proposal index (every track on the record)

| # | Track | Tier | Status |
|---|-------|------|--------|
| [P-001](proposals/P-001-csharp-extractor.md) | C# → OwnIR extractor (WPF leak spike) | P0 | in progress (well past v0: WPF001–005 + DI graph + pool + flow facts + semantic resolution) |
| [P-002](proposals/P-002-verification-backend.md) | Verification backend (Boogie/Dafny) | horizon | draft |
| [P-003](proposals/P-003-lifetime-visualization.md) | Lifetime visualization (RustOwl-style) | horizon | draft |
| [P-004](proposals/P-004-wpf-lifetime-profile.md) | WPF / UI lifetime leak profile | P0 | in progress (WPF001–005 built) |
| [P-005](proposals/P-005-idisposable-ownership.md) | `IDisposable` ownership profile | P0 | in progress (D1/D2 built via WPF003; D3/D4 path-sensitive via `--flow-locals`) |
| [P-006](proposals/P-006-di-lifetimes.md) | DI lifetime / captive dependency | P0 | in progress (DI001–DI005 end-to-end: core + extractor) |
| [P-007](proposals/P-007-arraypool-span.md) | ArrayPool / Span borrow-view | P1 | in progress (POOL001–003 built; 004/005 first slices) |
| [P-008](proposals/P-008-effects-and-resources.md) | Effects & resources (`Own.Effects`) | P1/P2 | draft |
| [P-009](proposals/P-009-nogc-regions.md) | No-GC / allocation-free regions | horizon | draft |
| [P-010](proposals/P-010-type-disciplines.md) | Richer type disciplines (`Own.Types`) | P2/horizon | draft |
| [P-011](proposals/P-011-editor-tooling.md) | Editor tooling & syntax highlighting | side-track | draft |
| [P-012](proposals/P-012-bug-corpus-mining.md) | Real-world bug corpus & mining | enabling | in progress (corpus benchmark + real-world cases, CI-gated) |
| [P-013](proposals/P-013-distribution-surface.md) | Distribution surface (CI Action + dotnet tool) | enabling | v0 built |
| [P-014](proposals/P-014-semantic-resolution.md) | Project-local semantic resolution (`+=` event vs number) | P0 | in progress (Tier A default-on + Tier B light path `--ref-dir`; full MSBuild closure deferred) |
| [P-015](proposals/P-015-configuration-surface.md) | Configuration surface (check selection & severity) | P2 | draft (stub) |
| [P-016](proposals/P-016-deep-fact-extraction.md) | Deep C# fact extraction (CFG + flow lowering) | P1 | in progress (B0a/B0b/B2/A1 via `--flow-locals`) |
| [P-017](proposals/P-017-multi-stack-frontends.md) | Multi-stack frontends (OwnTS / OwnJVM: OwnJava + OwnKotlin) | horizon | draft |
| [P-020](proposals/P-020-ownts-react-effects.md) | OwnTS React effects profile (`Own.React`) — effect-storm angle | horizon | draft |
| [P-021](proposals/P-021-async-audit-pack.md) | Async audit pack (`Own.Async`) — safety-first WPF/application async lifecycle diagnostics | P2 | draft |
