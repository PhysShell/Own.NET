# P-004 — WPF / UI lifetime leak profile

- **Status:** in progress (P0) — WPF001 (v0) + **WPF002 (timer)** + **WPF003
  (IDisposable field)** + **WPF004 (ignored Subscribe)** + **self-owned & static-
  handler exemptions (P-014 Tier A) built**; **WPF005 (escape → OWN014): bridge +
  core half built** — a `capture` fact routes through the region engine; the
  extractor pattern-matcher that emits it is the remaining increment
- **Depends on:** [P-001](P-001-csharp-extractor.md) (the extractor + OwnIR seam),
  `spec/OwnCore.md`, `spec/Lifetimes.md` (OWN001 leak, OWN014 region escape).
  See [`docs/ROADMAP.md`](../ROADMAP.md) for where this sits (Milestones 1–2).

## Motivation

The most emotionally useful result Own.NET can produce is not "our DSL correctly
rejected release-after-move" — it is **"Own.NET found a potential memory leak in
*our real* WPF code"**. Desktop XAML apps leak the same way over and over: a
short-lived View/ViewModel subscribes to a long-lived source and is never
collected. The platform's analyzers mostly stay silent here.

P-001 v0 already lands the first pattern (`event += without -=`) end-to-end. This
proposal is the rest of the WPF *profile*: the small set of C# patterns that
actually kill memory, expressed as ordinary resource facts so they reuse the one
core, not a bespoke "WPF engine".

## Scope (the four-rule profile)

Recognised in classes that look like lifetime-bound components (heuristic: name
ends `ViewModel`/`View`, derives `Window`/`UserControl`/`Page`, implements
`INotifyPropertyChanged`):

| Rule | Pattern | Core verdict |
|------|---------|--------------|
| **WPF001** | `source.Event += handler` with no matching `-=` in `Dispose`/`OnClosed`/`Unloaded` | `OWN001` (leak) ✅ v0 |
| **WPF002** | `DispatcherTimer`/`Timer` `Tick`/`Elapsed` handler with no `-=` and no `Stop()` | `OWN001` `[resource: timer]` ✅ |
| **WPF003** | an `IDisposable` field the class `new`s but never disposes | `OWN001` `[resource: disposable field]` ✅ (core of P-005) |
| **WPF004** | `X.Subscribe(...)` whose `IDisposable` result is ignored (bare statement) | `OWN001` `[resource: subscription token]` ✅ |
| **WPF005** | strong capture by a longer-lived source (the ViewModel `escapes` to App) | `OWN014` ✅ bridge+core (extractor pending) |

Modelled as resource facts (no new magic — the resource is just named
`Subscription`):

```text
event +=            -> acquire(Subscription, loc)
event -=            -> release(Subscription, loc)
token.Dispose()     -> release(Subscription, loc)
owner(this, Subscription)
escapes(this, App)  -> a strong capture by a longer-lived source  (feeds OWN014)
Dispose/OnClosed/Unloaded -> a permitted release region
```

**Lifetime exemptions (built, P-014 Tier A).** Two sound, syntax-cheap cases where
a `+=` without `-=` is provably *not* a leak and is dropped — decided semantically
(symbols, not text):
- **Self-owned source** — the event source is `this`, or a field/local the class
  constructs (and so owns); the `source <-> this` cycle outlives nothing and is
  GC-collectable.
- **Static handler** — `+= StaticMethod` stores a delegate whose `Target` is null,
  so no instance is retained, however long-lived the source.

Timers are excluded from both (a *running* timer is dispatcher-rooted regardless).
Samples: `SelfOwnedViewModel.cs` / `StaticHandlerViewModel.cs` (silent) vs
`CustomerViewModel.cs` (injected instance source → leak). On GTM these keep
`VCreate`/`VRibbon`'s *instance* subscriptions to the static
`LicContext.LicenseDataChanged` as leaks, while dropping the static-class
`Context`'s subscription to the *same* event — the deciding factor is the
subscriber/handler, not the source.

The corpus already pins three of these against real core codes:
`corpus/wpf/zombie-viewmodel` (OWN001), `viewmodel-escapes-to-app` (OWN014),
`handler-use-after-dispose` (OWN002). WPF004 is built; **WPF005's bridge + core
half is now built too**: a `capture` OwnIR fact (a *tokenless* strong subscription
tagged with its source's lifetime class) routes through the region engine
(`ownlang/lifetimes.py`) and surfaces as `OWN014` at the C# line — pinned by
`tests/fixtures/ownir/capture.facts.json` (a `static`/process-lived source escapes;
an injected-lifetime source stays conservatively silent). The remaining increment
is the extractor emitting that fact (a `+=` to a static event); until then it is
exercised by hand-written facts, exactly as each prior pattern was before its
matcher landed. This makes the WPF escape a *profile* of the general region model
(`subscribe self to <source>`), not a bespoke path — the ROADMAP Milestone-2 goal.

## Non-goals

XAML analysis, the binding engine, the visual tree, routed events, dependency
properties, `WeakEventManager` inference, Rx beyond `IDisposable`, and every
event-aggregator library in existence. That road ends in a +2400-line PR where
codegen double-returns an `ArrayPool`, only now with `DispatcherObject`. A
`[OwnIgnore("source lifetime is shorter")]` attribute is the escape hatch.

## Sketch

The seam is already built (P-001): Roslyn extractor → versioned OwnIR JSON →
core → diagnostic at the C# line. This profile = (a) more `acquire`/`release`
pattern matchers in the extractor (timer start/stop, ignored `Subscribe` result,
disposable subscription field), and (b) emitting the `owner`/`escapes` lifetime
facts so OWN014 fires for WPF005.

```text
*.cs --[extractor: += / Tick+Start / Subscribe / field / escapes]--> facts.json
     --[core]--> OWN001 (leak) / OWN014 (escape) @ C# line
```

Land **one pattern per increment** (WPF002/003/004 built — a `Tick`/`Elapsed`
handler is a `Timer`; a `new`'d-and-undisposed `IDisposable` field is a
`Disposable`; an ignored `X.Subscribe(...)` is a dropped subscription token;
WPF005 escape next), each with `bad`/`ok` samples, exactly as v0 did.
WPF003 overlaps the
general `IDisposable`-field rule in [P-005](P-005-idisposable-ownership.md); build
it once in the resource core and let WPF consume it as a profile.

## Open questions

1. Heuristic vs annotation for "this class is a lifetime-bound component"
   (name/base/interface heuristic for v0; `[OwnComponent]` opt-in later).
2. Where does the release region end — accept `Dispose`/`OnClosed`/`Unloaded`/
   `Unloaded` only, or any method named `Dispose*`? (Conservative set first.)
3. WPF005 needs a lifetime ordering (`Subscriber < Process`). **Resolved for the
   first source class:** the bridge *infers* it from the source kind — a `static`/
   process-lived event is the longest region and strictly outlives any subscriber,
   so `subscribe self to <static source>` → OWN014 with no annotation. Other source
   classes (an injected source of unknown lifetime → conservatively silent today; a
   parent scope) are later increments. A single shared `Subscriber` region suffices
   while there is one source region; multiple source regions will want a per-source
   ordering (the `< LONGER` form takes one edge per decl).
4. `WeakEventManager` / weak subscription as an *accepted* release — recognise it
   as "not a leak" to cut false positives, without modelling its internals.
