# P-001 — C# → OwnIR extractor (the WPF leak spike)

- **Status:** in progress — **v0 built** (`event += without -=`). Seam and v0
  scope decided as recommended below.
- **Depends on:** `spec/OwnCore.md`, `spec/Lifetimes.md` (the fact vocabulary)

## What is built (v0)

The `event += without -=` pattern, end-to-end, exactly along the recommended
seam:

- **Roslyn extractor** (`frontend/roslyn/OwnSharp.Extractor`, C#, syntax-only):
  scans `.cs`, emits OwnIR facts (JSON) — built & run in CI (`wpf-extractor`).
- **Python fact bridge** (`ownlang/ownir.py`, `python -m ownlang ownir`): lowers
  facts to a synthetic `.own` sketch, runs the **existing core**, and maps the
  OWN001 verdict back to the C# location with the `[resource: subscription
  token]` tag. Tested locally against hand-written facts (`tests/test_ownir.py`).
- **CI** (`wpf-extractor` job): real `.cs` → extractor → facts → core → leak at
  its C# line; the disposed sample stays silent.

Next: `IDisposable` fields, and feeding region facts to OWN014 (timers built —
the WPF002 increment, see [P-004](P-004-wpf-lifetime-profile.md)).

## Motivation

Today OwnLang catches real bug *patterns*, but only on hand-written `.own`: there
is no C# front-end, so the corpus is hand-reduced. The highest-value next step —
and the one that turns "our DSL correctly rejected release-after-move" into
"Own.NET found a leak in **our real code**" — is ingesting actual C# for the
narrow class of leaks the core already models: event subscriptions, timers,
`IDisposable` fields, ignored `Subscribe` results.

This is **not** a full C# ownership front-end (generics, async, dataflow — that is
human-years and explicitly rejected). It is a syntactic/local pattern extractor.

## Scope (v0)

Recognize, in classes that look like ViewModels/Views (heuristic: name ends
`ViewModel`/`View`, derives `Window`/`UserControl`/`Page`, implements
`INotifyPropertyChanged`):

- `source.Event += handler` with no matching `-=` in a `Dispose`/`OnClosed`/
  `Unloaded` body;
- `Subscribe(...)` whose `IDisposable` result is ignored;
- (next) `DispatcherTimer` started with no `Stop`/`Tick -=`;
- (next) an `IDisposable` field with no cascade `Dispose`.

Emit these as **OwnIR facts in the spec's vocabulary** (so DSL, C# and any future
front-end speak one language):

```text
acquire(Subscription, loc)        // event += / Subscribe(...)
release(Subscription, loc)        // event -= / token.Dispose()
owner(this, Subscription)
escapes(this, App)                // strong capture by a longer-lived source
```

In v0 the existing core produces `OWN001` (no release path) with the
`[resource: subscription token]` kind tag. `OWN014` (region escape) is enabled
once the extractor emits the `escapes(...)`/lifetime facts above — that is the
next increment, not v0.

## Non-goals

XAML / binding engine / visual tree / routed events / dependency properties /
`WeakEventManager` inference / Rx beyond `IDisposable` / every event-aggregator
library. A `[OwnIgnore("reason")]` suppression attribute is the escape hatch.

## Sketch / architecture

**Recommended seam:** Roslyn (C#) extractor → OwnIR facts (JSON) → the existing
Python core checks them and renders diagnostics. Do **not** reimplement the
checker in C# (a second checker drifts from the core — the project's own
meta-irony). The two meet through OwnIR, exactly as `spec/` enables.

```text
*.cs --[Roslyn extractor (C#)]--> facts.ownir.json --[Python core]--> OWN001/OWN014
```

**Environment note:** this sandbox has `dotnet` only in CI (the `dotnet-golden`
job). So: build and fully test the **Python fact-ingest** locally against
hand-written `facts.ownir.json` fixtures now; the Roslyn extractor is a
CI-validated C# artifact (like the golden). Land **one pattern** first
(`event += without -=`) end-to-end before adding timers/fields.

## Open questions

1. ~~**Seam:** confirm `C# extractor → OwnIR → Python core` (vs all-in-C#).~~
   **Resolved:** extractor → versioned OwnIR JSON → Python core. The core also
   exposes an AST-level entry (`__main__.check_module`) so the next pattern can
   build a module directly instead of round-tripping through `.own` text.
2. **v0 scope:** one pattern first, or the four-rule set in one go.
3. ~~**OwnIR serialization:** JSON schema vs emitting `.own` directly.~~
   **Resolved:** JSON, stamped with `ownir_version` (`OWNIR_VERSION`, currently
   0). A mismatched extractor/core pair fails loudly at load instead of being
   silently mis-read; the bridge maps verdicts back to C# by the diagnostic's
   structured `subject`, not by scraping the human message.
4. Heuristic vs annotation for "this class is a lifetime-bound component".
