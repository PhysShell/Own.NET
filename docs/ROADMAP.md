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
borrow checker is the *first combat module*, not the whole universe. The
long-term identity the backlog is aiming at:

> **An external static-contract layer for C#/.NET** that adds ownership,
> typestate, effects, capabilities, and domain-specific types **without
> rewriting the codebase.**

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
  "understand C#" (SemanticModel hides async, generics, LINQ, closures, pattern
  matching, overload resolution, nullable flow, source generators…). Its job is
  to extract *facts*: acquire / borrow / use / release / escape / control-flow.
- **Refuse the soul-eating version.** Every proposal's Non-goals section is the
  most important one. Boredom keeps projects alive.

### What the C# frontend deliberately does NOT touch yet

`async`/`await`, full generics, LINQ, closures/lambdas, interprocedural analysis,
virtual dispatch, whole-program analysis, source generators, `unsafe` pointer
arithmetic, the XAML/binding engine. Not "never" — just not *before* the tool has
found its first real bug. An `async` method in v0 is honestly skipped (or flagged
"unsupported"), because honestly skipping beats confidently lying; the market for
confident-but-wrong tooling is already saturated.

## Priorities

Targets are ranked by four criteria: (1) the pain is frequent or expensive,
(2) it is at least partly catchable *statically*, (3) it maps cleanly onto
ownership/lifetime/effects, (4) an MVP needs no PhD in Roslyn.

| Tier | Targets | Proposal |
|------|---------|----------|
| **P0** | WPF/event/timer/subscription leaks; `IDisposable` ownership (leaks, fields, use-after-dispose); DI lifetime mismatch (captive dependency) | [P-004](proposals/P-004-wpf-lifetime-profile.md), [P-005](proposals/P-005-idisposable-ownership.md), [P-006](proposals/P-006-di-lifetimes.md) |
| **P1** | ArrayPool/Span ownership-view bugs; hidden effects / architecture rules | [P-007](proposals/P-007-arraypool-span.md), [P-008](proposals/P-008-effects-and-resources.md) |
| **P2** | async resource lifecycle; `ValueTask` affine usage; typestate/protocols | [P-008](proposals/P-008-effects-and-resources.md), [P-010](proposals/P-010-type-disciplines.md) |
| **P3** | LOH fragmentation; static-collection memory bloat; cross-thread `ObjectDisposedException` | — (runtime-bound; see detectability matrix) |

**The five concrete diagnostics to build first** (balanced across real pain,
architectural strictness, and the borrow-checker showcase):

1. `WPF001` — event/subscription `+=` without `-=` (the WPF spike; P-001 v0 ✅)
2. `WPF002` — `DispatcherTimer`/`Timer` `Tick`/`Elapsed` without stop/detach ✅
3. `OWN001` — `IDisposable` field the class `new`s but never disposes ✅
4. `DI001` — singleton captures a scoped dependency ✅ (core check built;
   C# registration-graph extractor pending)
5. `POOL001` — `ArrayPool` buffer `Rent`ed but never `Return`ed ✅
   (`POOL002` `Span`/view used after `Return` next)

### Milestones

1. **WPF leak spike** — find 1–3 real subscription/timer leaks in real code (P-004).
2. **Resource core** — generalise WPF subscriptions + `IDisposable` into one
   acquire/release/owner/release-region model (P-004 ∪ P-005), so WPF is a
   *profile*, not a one-off.
3. **DI lifetimes** — registration + constructor graph; captive dependency (P-006).
4. **Pool/Span** — `Rent`/`Return`, borrowed views, return-invalidates-views,
   known-bug replay corpus (P-007). The borrow checker on stage at full height.
5. **Effects** — `pure` / `use !Db` / `use !Log` / `use Clock`, layer policies
   (P-008). The architectural X-ray — landed *after* the leak checkers prove value.

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
| [P-001](proposals/P-001-csharp-extractor.md) | C# → OwnIR extractor (WPF leak spike) | P0 | in progress (v0 built) |
| [P-002](proposals/P-002-verification-backend.md) | Verification backend (Boogie/Dafny) | horizon | draft |
| [P-003](proposals/P-003-lifetime-visualization.md) | Lifetime visualization (RustOwl-style) | horizon | draft |
| [P-004](proposals/P-004-wpf-lifetime-profile.md) | WPF / UI lifetime leak profile | P0 | draft |
| [P-005](proposals/P-005-idisposable-ownership.md) | `IDisposable` ownership profile | P0 | draft |
| [P-006](proposals/P-006-di-lifetimes.md) | DI lifetime / captive dependency | P0 | in progress (DI001 core check built) |
| [P-007](proposals/P-007-arraypool-span.md) | ArrayPool / Span borrow-view | P1 | draft |
| [P-008](proposals/P-008-effects-and-resources.md) | Effects & resources (`Own.Effects`) | P1/P2 | draft |
| [P-009](proposals/P-009-nogc-regions.md) | No-GC / allocation-free regions | horizon | draft |
| [P-010](proposals/P-010-type-disciplines.md) | Richer type disciplines (`Own.Types`) | P2/horizon | draft |
| [P-011](proposals/P-011-editor-tooling.md) | Editor tooling & syntax highlighting | side-track | draft |
| [P-012](proposals/P-012-bug-corpus-mining.md) | Real-world bug corpus & mining | enabling | draft |
| [P-013](proposals/P-013-distribution-surface.md) | Distribution surface (CI Action + dotnet tool) | enabling | v0 built |
| [P-014](proposals/P-014-semantic-resolution.md) | Semantic resolution for the C# extractor | P0 | draft |
