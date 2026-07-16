# P-035 — Project-declared weak-subscription conventions

- **Status:** partially implemented. **B0+B1 shipped** — a project declares its
  weak-subscribe wrapper API in `own.toml` (`[weak-subscription].subscribe`), read via
  `own-check --config`, and the extractor mints a matching call as a first-class,
  already-released subscription. **Increment A** (unsubscribe wrapper — needs event
  identity first) and **Increment C** (project-aware fix text / 007 wiring) remain
  **deferred**, as does a general `AddHandler` heuristic.
- **Depends on / reconciles with:**
  - [P-004](P-004-wpf-lifetime-profile.md) — the WPF lifetime profile. Its Open
    Question #4 (P-004:142-143) proposes recognising *"`WeakEventManager` / weak
    subscription as an accepted release … without modelling its internals"*, and
    lists `WeakEventManager` inference as an explicit non-goal (P-004:99-100). This
    proposal is the concrete, generalised form of #4: the release is not only the
    BCL `WeakEventManager`, it is **whatever weak-subscribe API a given repo uses**.
  - [P-015](P-015-configuration-surface.md) — the per-project config surface
    (`.ownrc` / `own.toml`). The weak-subscribe convention is a natural resident of
    that file; this proposal must land *in* that surface, not invent a second one.
  - [P-014](P-014-semantic-resolution.md) — Tier-A `+=` subscription resolution.
    The recognition half here needs the symmetric step P-014 never took: seeing a
    **method-call** subscription (`Mgr.AddHandler(src, h)`), not only `event += h`.
  - The two shipped precedents this mirrors, both in
    `frontend/roslyn/OwnSharp.Extractor/Program.cs`: the `#223` curated
    weak-referenced-static-event allowlist (`IsWeakReferencedStaticEvent`, :773) and
    the `#209` `[OwnIgnore("reason")]` attribute the extractor already reads
    (`OwnIgnoreReason`, :4388).

## Motivation — a real codebase proved the BCL manager is not universal

P-004 #4 assumed the accepted weak release *is* `System.Windows.WeakEventManager`
(or `PropertyChangedEventManager`). A real-world conversion showed that assumption
is too narrow, in a way that is not academic.

A customs-broker WPF application (net472) has the archetypal static-publisher leak:
every document object subscribes in its **constructor** to a process-lived settings
publisher (`AppData.Properties.GBProperty.PropertyChanged += …`) and is detached
only on the display path — so every document built on a background/import path and
dropped leaks its whole object graph. The obvious "fix it with weak events" answer
was tried with the BCL managers and **failed for two independent, concrete
reasons**:

1. **Thread affinity.** `WeakEventManager` (base, generic `WeakEventManager<,>`, and
   `PropertyChangedEventManager` alike) keeps per-thread bookkeeping. These
   constructors run on **background threads** (cloud sync builds the document inside
   `Task.Run`), while the setting is toggled on the UI thread. The WPF weak-event
   infrastructure is designed around a single (UI) thread; a background-thread
   subscription is exactly the case it does not promise to serve.
2. **Assembly resolution.** The managers live in WindowsBase / `System.Windows`, and
   in that project's data-layer assembly they did **not even resolve in the WPF
   markup-compile pass** — the build failed outright.

The project's correct fix was a **small, thread-agnostic, hand-rolled weak
forwarder** (`WeakEvents.AddPropertyChanged(source, handler)` — the publisher holds
a strong ref only to a tiny forwarder that holds a `WeakReference` to the listener
and unhooks itself once the listener dies), validated by a `WeakReference`+GC test
(collected with no explicit detach), a cross-thread-delivery test, and a
safe-after-collection test — all green.

The lesson for Own.NET: **the accepted weak release is project-specific.** A tool
that only knows `WeakEventManager` will (a) mis-suggest a fix that does not compile
or does not work in that codebase, and (b) — once method-call subscriptions are
seen at all — fail to recognise the project's own weak wrapper as a release, and
re-flag correctly-fixed code. The escape hatch already exists for suppression
(`[OwnIgnore]`); what is missing is a way to declare *"this is how we subscribe
weakly here."*

## What exists today (so this does not re-invent a seam)

- **Publisher-side weak recognition** — `IsWeakReferencedStaticEvent`
  (`Program.cs:760-776`, issue #223): a curated allowlist of BCL/WPF *static events*
  whose publisher holds subscribers weakly (one entry: `CommandManager.RequerySuggested`).
  Deliberately curated and compiled-in — "extend only when another sibling's
  weak-reference implementation is independently confirmed."
- **Subscription detection** — the C# `event += handler` operator mints an `acquire`
  (P-014 Tier A). In addition, **B1** now mints one for a **declared** weak-subscribe
  wrapper *method call* (`MatchesDeclaredWeakSubscribe`): an exact `(containing-type
  simple name, method name)` on the allowlist, with the MVP `(source, handler)`
  positional contract and a real handler second argument (`IsHandler`), resolved via
  the method symbol or a syntactic receiver-name fallback for an unresolved external
  package. A non-declared method call is still invisible; there is **no** general
  `AddHandler` heuristic. The Rx `X.Subscribe(…)` IDisposable-token shape is unchanged,
  and a declared wrapper named `Subscribe` is suppressed there so it is not
  double-counted.
- **Per-site suppression** — `[OwnIgnore("reason")]` is read from source
  (`OwnIgnoreReason`, `Program.cs:4388`, issue #209).
- **A project-wide config is now consumed (B0)** — `own-check --config own.toml` reads
  the `[weak-subscription].subscribe` allowlist (`ownlang/config.py`, `tomllib`; a
  malformed table is a hard error) and forwards it to the extractor via the internal
  `--weak-subscribe` transport flag. This is the first, deliberately narrow slice of
  P-015; discovery / severity / per-path / env stay deferred there. The composite
  Action exposes it as the optional `config:` input.

The two consumers this proposal named — recognition (shipped, B1) and fix text
(deferred, Increment C) — now sit on that config seam.

## Design

### 1. The declaration (in P-015's config surface)

A repo declares its weak-subscribe convention once, e.g.:

```toml
# own.toml  (P-015)
[weak-subscription]
subscribe   = ["WeakEvents.AddPropertyChanged"]   # (containing-type simple name, method name)
unsubscribe = ["WeakEvents.RemovePropertyChanged"]
```

Matching is by **(containing-type simple name, method name)**, identical to the
`#223` / `#228` allowlist shape and the `[OwnIgnore]` simple-name precedent — chosen
because the declaring package usually does not resolve on the CI runner. This is a
**data allowlist, never an inference**: absence keeps today's honest behaviour.

### 2. Recognition consumer (cut false positives on already-fixed code)

Two sub-parts, both small and both gated on the config being present (zero change
when it is absent):

- **See the subscribe call.** Extend the invocation-handling path (next to the
  existing `Subscribe` matcher) to mint a subscription `acquire` when the call's
  `(type, method)` is on the declared `subscribe` list — so the tool can reason
  about it at all.
- **Mark it released.** A subscription made through a declared weak `subscribe` is an
  **accepted release** — set the same `released` boolean the `-=` path sets
  (`Program.cs:3553`, consumed at `ownir.py:779-780, 940-941`), so it never becomes
  OWN001/OWN014. This is the subscriber-side sibling of `#223`, and — unlike `#223`
  — it is config-extensible rather than curated, because a project's own wrapper
  cannot be "independently confirmed" in Own.NET's tree.

> Note: **before B1** a converted call was silent only by accident — the extractor saw
> only `event += handler`, so a method-call wrapper was *invisible* (no fact at all).
> **B1 (shipped in this PR) removes that**: the extractor now detects a declared wrapper
> call and emits it as a first-class, `released:true` subscription. So the wrapper is
> silent-and-**recognised** (an auditable release), not silent-and-invisible — and a
> mixed `+=`/wrapper codebase is no longer half-analysed.

### 3. Fix-text / autofix consumer (suggest the *project's* weak API)

Own.NET does not ship a code-fix (by policy — the fix is applied by an agent under
the 007 harness's `o7 run`). Two touch-points:

- **The OWN001 explanation** (`ownlang/diagnostics.py:122-130`) currently offers a
  fixed *"unsubscribe (`-=`) in Dispose/Unloaded, dispose the owned field in the
  owner's Dispose, or capture and dispose the IDisposable a `Subscribe()` returns"*
  text — it names **no** weak-events manager at all today. Increment C would make it
  name the project's **declared** `subscribe` API as the weak alternative when a
  `[weak-subscription]` convention is configured (rather than hard-coding the BCL
  `WeakEventManager`, which the STS case proves may not fit).
- **The agent fix task** (007) should be handed the convention so a converting agent
  emits `WeakEvents.AddPropertyChanged`, not a `WeakEventManager` that — as the STS
  case proves — may not compile or may not work in that layer.

## Corpus

`corpus/wpf/custom-weak-wrapper/` accompanies this proposal: the leaky `+=` form
(OWN001), the fixed form through a project weak wrapper (expected: silent — accepted
release), the `.own` reduction, and notes tying it to the STS finding. It is the
regression fixture for the recognition half.

## Non-goals

- **Modelling the wrapper's internals.** Like `#223`, this trusts a declared name;
  it does not verify that `WeakEvents.AddPropertyChanged` is *actually* weak. A wrong
  declaration is the project's responsibility, exactly as a wrong `[OwnIgnore]` is.
- **A general method-call subscription model.** Only declared `(type, method)` pairs
  (plus the existing Rx `Subscribe`) are minted as subscriptions; a full "any
  `AddHandler`-shaped call is a subscription" inference is out of scope.
- **Shipping a weak-events helper.** Own.NET recommends a shape; the project owns the
  implementation (cf. P-027's stance that Own.NET ships no mandated fix type).

## Resolved decisions

1. **Config format & discovery — RESOLVED.** The carrier is an **explicit
   `own-check --config own.toml`** (no auto-discovery). Format is **TOML**
   (`tomllib`), the minimal P-015 slice — see [P-015](P-015-configuration-surface.md).
2. **Method-call subscription detection — RESOLVED: folded into P-035**, not carved
   out as a separate P-014 increment. It has *no* standalone behaviour — it fires only
   for an explicitly declared `(type, method)` pair, so it cannot exist without a
   P-035 declaration.

## Open questions (deferred)

- **Increment A** — should a declared `unsubscribe` also be recognised as a release
  for a *`+=`* subscription (a project that hides `-=` behind
  `WeakEvents.RemovePropertyChanged`)? **Deferred**: `(source, handler)` alone cannot
  pin the release to a specific `event +=` on the same source, so a sound design needs
  event identity first (arbiter). Not implemented.
- **Increment C** — the project-aware fix text (the OWN001 explanation naming the
  declared API instead of `WeakEventManager`) and the 007 fix-agent wiring. **Deferred**
  to a separate scope with write-capable remediation plumbing.
