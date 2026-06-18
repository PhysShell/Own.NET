# P-004 — WPF / UI lifetime leak profile

- **Status:** in progress (P0) — WPF001 (v0) + **WPF002 (timer)** + **WPF003
  (IDisposable field)** + **WPF004 (ignored Subscribe)** + **self-owned & static-
  handler exemptions (P-014 Tier A) built**; **WPF005 (escape → OWN014) built
  end-to-end** — the extractor lowers a static-event `+=` to a `capture` fact that
  the region engine reports as OWN014 (a released `-=` mitigates it -> silent)
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
| **WPF005** | strong capture by a longer-lived source (the ViewModel `escapes` to App) | `OWN014` ✅ end-to-end (extractor emits `capture` for a static-event `+=`) |

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

The corpus pins four of these against real core codes: `corpus/wpf/zombie-viewmodel`
(OWN001), `viewmodel-escapes-to-app` (OWN014), `handler-use-after-dispose` (OWN002),
and **`systemevents-region-escape` (OWN014)** — the SystemEvents leak seen through
the region model, the same bug `corpus/real-world/screentogif-systemevents-leak`
shows through the token model.

**WPF004 and WPF005 are now built end-to-end.** WPF005's contract splits strictly by
the source's lifetime — the extractor classifies the `+=`, the core decides — and
the three cases do **not** overlap:

- **static / process-lived source** (a static event, or a static field/property
  receiver) → a *tokenless* `capture` fact → the region engine promotes the
  subscriber to the longer region → **OWN014** (a hard leak). The engine would stay
  silent for an equal-or-shorter-lived source, but the extractor only routes
  provably-longer (process-lived) sources into it, so every emitted `capture`
  escapes unless released.
- **injected / unknown-lifetime source** → stays a token `subscription` → **OWN001
  at the WARNING tier** — an honest "may outlive this", **not** silent and **not**
  OWN014 — until ownership modelling can prove or refute the source's lifetime.
- **a matching `-=` (`released`)**, on either path → mitigated → **silent**.

So a reader should infer neither that OWN014 applies to every subscription, nor that
an injected subscription is silent: the source kind picks the path. Exercised by the
`capture` fixture (`tests/fixtures/ownir/capture.facts.json`) and the
`StaticEventEscapeViewModel` sample (CI `wpf-extractor`, asserting OWN014 on the
instance handler and silence on the unsubscribed one). This makes the WPF escape a
*profile* of the general region model (`subscribe self to <source>`), not a bespoke
path — the ROADMAP Milestone-2 goal.

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
disposable subscription field) — built; and (b) emitting the region-escape fact
(a static-source `+=` → a `capture`) so OWN014 fires for WPF005 — built: a
static event/static-receiver subscription is the `capture`, the bridge maps its
`source` to a process-lived region and the engine reports the promotion.

```text
*.cs --[extractor: += / Tick+Start / Subscribe / field / escapes]--> facts.json
     --[core]--> OWN001 (leak) / OWN014 (escape) @ C# line
```

Land **one pattern per increment** (WPF002/003/004/005 built — a `Tick`/`Elapsed`
handler is a `Timer`; a `new`'d-and-undisposed `IDisposable` field is a
`Disposable`; an ignored `X.Subscribe(...)` is a dropped subscription token; a
static-event `+=` is a `capture` → region escape), each with `bad`/`ok` samples,
exactly as v0 did. WPF003 overlaps the
general `IDisposable`-field rule in [P-005](P-005-idisposable-ownership.md); build
it once in the resource core and let WPF consume it as a profile.

## Open questions

1. Heuristic vs annotation for "this class is a lifetime-bound component"
   (name/base/interface heuristic for v0; `[OwnComponent]` opt-in later).
2. Where does the release region end — accept `Dispose`/`OnClosed`/`Unloaded`
   only, or any method named `Dispose*`? (Conservative set first.)
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
