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
| **P2** | async resource lifecycle; `ValueTask` affine usage; typestate/protocols | [P-008](proposals/P-008-effects-and-resources.md), [P-010](proposals/P-010-type-disciplines.md) |
| **P3** | LOH fragmentation; static-collection memory bloat; cross-thread `ObjectDisposedException` | — (runtime-bound; see detectability matrix) |

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
   `corpus/wpf/systemevents-region-escape` reduction (P-004 WPF005 ✅). Remaining:
   migrating the *injected*-source subscription tier (today an honest OWN001
   warning) once lifetime modelling can prove or refute those sources.
3. **DI lifetimes** — registration + constructor graph; captive dependency (P-006).
   ◑ *In progress* — DI001 lands end to end: the C# extractor builds the
   registration + constructor graph from `Add{Singleton,Scoped,Transient}` (generic
   and `typeof(...)` forms) and the core flags the captive — direct, transitive
   through a transient, or through an interface registration — CI-validated on
   `DiCaptiveSample.cs`. **DI003** (a transient `IDisposable` captured by a singleton,
   warning) now also fires on the same sample. Remaining: DI002 (weak-ref), the explicit
   root-`GetService` form of DI003, and the consuming-constructor anchor.
4. **Pool/Span** — `Rent`/`Return`, borrowed views, return-invalidates-views,
   known-bug replay corpus (P-007). The borrow checker on stage at full height.
   ◑ *In progress* — POOL001 (leak), POOL002 (view-after-return → OWN002),
   POOL003 (double-return/dispose, ArrayPool *and* MemoryPool) built end to end;
   POOL004 (view escape) and POOL005 (full-length over-read) first slices built.
   Remaining: POOL005 view stored in a FIELD, deeper POOL004 escape, and the
   real-world replay targets (dotnet/runtime, Nethermind, AiDotNet.Tensors).
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
| [P-004](proposals/P-004-wpf-lifetime-profile.md) | WPF / UI lifetime leak profile | P0 | in progress (WPF001–005 built) |
| [P-005](proposals/P-005-idisposable-ownership.md) | `IDisposable` ownership profile | P0 | draft |
| [P-006](proposals/P-006-di-lifetimes.md) | DI lifetime / captive dependency | P0 | in progress (DI001 end-to-end: core + extractor) |
| [P-007](proposals/P-007-arraypool-span.md) | ArrayPool / Span borrow-view | P1 | in progress (POOL001–003 built; 004/005 first slices) |
| [P-008](proposals/P-008-effects-and-resources.md) | Effects & resources (`Own.Effects`) | P1/P2 | draft |
| [P-009](proposals/P-009-nogc-regions.md) | No-GC / allocation-free regions | horizon | draft |
| [P-010](proposals/P-010-type-disciplines.md) | Richer type disciplines (`Own.Types`) | P2/horizon | draft |
| [P-011](proposals/P-011-editor-tooling.md) | Editor tooling & syntax highlighting | side-track | draft |
| [P-012](proposals/P-012-bug-corpus-mining.md) | Real-world bug corpus & mining | enabling | draft |
| [P-013](proposals/P-013-distribution-surface.md) | Distribution surface (CI Action + dotnet tool) | enabling | v0 built |
