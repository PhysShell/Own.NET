# Subscription leaks are a .NET concern, not a WPF one — codes vs. profiles

Prompted by a good question: should `event += without -=` be a `WPFxxx` error?
Short answer **no** — it is a general .NET lifetime/subscription bug, and the core
already treats it that way (`OWN001` + `[resource: subscription token]`, never a
"WPF" code). Recording the taxonomy so we don't re-open it, and so the *docs*
stop reading as if this were WPF-only when the capability is .NET-wide.

## What the core actually emits (we already did the right thing)

`event += without -=` lowers to a resource and comes out as **`OWN001`** with a
domain-neutral `[resource: kind]` tag — see the [README](../../README.md)
"Бизнес-применение" section and [P-001](../proposals/P-001-csharp-extractor.md):

```text
case.own:16: error: [OWN001] '…' is owned but not released … [resource: subscription token]
```

The `[resource: kind]` tag is the **seam**: the WPF profile (and the Roslyn
front-end) key off it without the core knowing a thing about WPF. That is already
in the README ("шов, за который зацепится WPF-профиль, не зная про WPF в ядре").

Crucially, the `WPF001..WPF005` in [P-004](../proposals/P-004-wpf-lifetime-profile.md)
are **profile rule mnemonics, not diagnostic codes** — its own table maps each one
to a core verdict:

```text
WPF001  source.Event += h, no matching -=        -> OWN001  [subscription token]
WPF002  Timer Tick/Elapsed, no Stop()/ -=        -> OWN001  [timer]
WPF003  owned IDisposable field, never Disposed  -> OWN001  [disposable field]
WPF004  ignored Subscribe() IDisposable token    -> OWN001  [subscription token]
WPF005  strong capture by a longer-lived source  -> OWN014  (region promotion)
```

So the core stays neutral; "WPF" is *recognition + lifetime context*, not the
error itself. The critique is correct, and we mostly already shipped it.

Since #278, "matching `-=`" is teardown-scoped, as the WPF001 row above always
said: the `-=` must sit in a recognised teardown context (`Dispose`/
`DisposeAsync`/`OnClosed`/`Unloaded`-style methods, a finalizer, a handler wired
to the class's own `Closed`/`Closing`/`Unloaded`-style lifecycle event, or a
method the teardown path calls intra-class) and must not be guarded by a
parameter of its enclosing method (the canonical positive `if (disposing)` of
`Dispose(bool)` excepted). A `-=` in an arbitrary method, or behind a
caller-controlled flag, is not proven to run and keeps the honest OWN001/OWN014
— the #238 doctrine: the worst case of an exemption must be "keeps today's
honest warning", never "silently swallows a leak class" (heap-proven on
SectorTS `GTD`, corpus: `subscription-param-guarded-unregister`,
`subscription-nonteardown-release`).

## The naming debt the critique correctly smells

The capability is general. The *same* `source.Event += h` without `-=` leaks in
**WinForms, Avalonia, MAUI, Unity, an ASP.NET singleton service, a console app
with an event bus** — anywhere a publisher outlives its subscriber. The Rx flavour
is `observable.Subscribe(x => …)` with the `IDisposable` token dropped. None of
that is WPF.

Yet P-001's subtitle ("the WPF leak spike"), P-004's `WPFxxx` rule names, and the
README's "WPF lifetime-утечки" heading make a .NET-wide analysis *read* as
WPF-only. That is naming a fire "kitchen thermodynamics." The fix is framing, not
the core: **"subscription / lifetime analysis with a WPF profile,"** not "WPF leak
analyzer."

## Proposed code families (direction, not a now-rename)

If/when the `[resource]` tag stops carrying enough and we want first-class codes:

```text
OWN   core ownership / borrow / release / lifetime promotion
SUB   subscriptions / events / observer tokens
TMR   timers
DI    dependency-injection lifetimes
POOL  ArrayPool / MemoryPool / Span storage
EFF   effects / resources
WPF   *truly* XAML-model retention (only the things below)
```

Today's profile rules would re-home cleanly: `WPF001 -> SUB001`,
`WPF002 -> TMR001`, `WPF004 -> SUB004` (ignored token), `WPF003 -> IDisposable
field (P-005)`, `WPF005 -> OWN014` (already neutral — it is lifetime promotion).

`WPFxxx` is genuinely *earned* only where the diagnostic needs the XAML object
model and cannot be a generic subscription/timer:

```text
DataContext retained after a View unloads
Binding / CollectionView keeping its source alive
ResourceDictionary / merged-dictionary retention
DependencyProperty metadata callback capturing an instance
Storyboard / animation / EventTrigger holding its target
WeakEventManager should have been used for a long-lived source
```

## OwnIR stays domain-neutral; the profile only adds heuristics

```text
core facts (neutral — what the extractor emits):
  acquire(subscription, loc)     release(subscription, loc)
  owner(this, subscription)      handler(subscription, h)    captures(h, this)
  source(subscription, publisher)
  lifetime(this, ViewModel)      lifetime(publisher, App)     # when known

wpf profile (heuristics layered on top — never inside the core):
  class *ViewModel  /  : Window|UserControl|Page  -> lifetime ViewModel / UI
  Application.Current  /  singleton service        -> lifetime App
  Dispose / OnClosed / Unloaded                    -> cleanup regions
  DispatcherTimer / WeakEventManager / …           -> WPF-specific sources
```

The same facts can later carry `profile = winforms | avalonia | maui | aspnet`
without touching the checker. One core; many profiles. The seam already exists.

## Severity follows what we can *prove* (the `OWN001` decision)

We keep the code `OWN001`. The open behavioural question was: do we always shout
`error` at a lambda handler? **No** — that would be "the analyzer named *молодец,
нашёл C#*," which users mute faster than WPF leaks its first ViewModel. Without
lifetime evidence, tier `OWN001`'s *severity* by what the source provably is:

```text
static event + retaining handler   -> error    process-lifetime: a provable leak — the
  (captures `this` or a local)                 handler pins the subscriber to the source
static event + non-retaining       -> silent   nothing is pinned: a static method (null
  handler (static method /                     delegate target) or a NON-capturing lambda
  non-capturing lambda)                        (closure analog of the static-method exempt)
field / ctor-param / property      -> warning  lifetime unknown — may leak if the
                                               source outlives `this`; an inline
                                               lambda has no handle to `-=` at all
local publisher                    -> drop     dies with the scope (today a false
                                               positive: `local` is not in the
                                               self-owned set, so it leaks-by-mistake)
this / constructed field           -> exempt   self-owned cycle, GC-collectable (P-004)
```

**Ledger (issue #199): the static tier keys on whether the handler RETAINS an
instance.** OWN014's premise is "the strong subscription pins the subscriber to the
source's (process) lifetime." A handler that retains **nothing** — a static method
(null delegate `Target`) or a **non-capturing lambda** — pins no subscriber, so the
premise fails and it is **silent**, the closure analog of the long-standing
static-method exemption (`StaticHandlerViewModel`). A handler that captures `this`
**or an enclosing local** (the CsvHelper `ConsoleHost` `cts`/`resetEvent` shape) does
pin state and stays **OWN014**. This is gated strictly through the extractor's
conservative `HandlerRetainsNoInstance` (Program.cs): any handler it cannot *prove*
non-retaining — a captured local, an opaque delegate-typed value — is treated as
retaining and still flags. It never widens the exemption syntactically (no
`clsIsStatic`, no "all lambdas"). Pinned by `AppDomainShutdownSample`
(`NonAppDomainSubscriber` capturing → OWN014, `NonCapturingStaticSubscriber` → silent).

**Deliberate non-goal — invocation-list growth from repeated non-capturing
subscriptions.** A non-capturing `+=` still *appends* a delegate to the event's
invocation list, and a hot path that re-subscribes (e.g. `+=` in the ctor of a
short-lived / transient object created many times) grows that list unbounded — a real
but *different* memory-growth shape (unbounded list length, not a pinned subscriber
instance) that the OWN014 region-escape model does not express. It was never covered
for the static-method exemption either, so silencing the non-capturing **lambda** is
*not* a regression relative to that. Recorded as a candidate in
[`field-notes-patterns.md`](field-notes-patterns.md); it would need its own signal
(a subscribe-in-a-hot-constructor heuristic), not the region model.

The punchline ties the two halves together: **the WPF profile is exactly the thing
that turns that `warning` back into an `error`.** When the profile (or an explicit
`lifetime` region) resolves the source to App-lifetime over a ViewModel subscriber,
the hedge becomes the confident verdict the core *already* produces — **`OWN014`**
(`App > ViewModel ⇒ promotion ⇒ leak`, see the README region example). "Warning
without a profile, error with one" is not a cop-out: it is the honest contract, and
the lifetime/region analysis is the upgrade path. Same mechanism, viewed twice.

This also keeps us consistent with our own line — honest-skip (`--stats`, `OWN050`)
and the oracle precision stance ([oracle.md](oracle.md): we ding Infer# for
ownership-transfer false positives). Erroring on every lambda would be us doing the
exact thing we flag the neighbours for.

## What to actually change — and what not to

- **Now (cheap, no code):** reframe the docs — P-001 subtitle, P-004 title and the
  table's column header, the README heading, `ROADMAP` — from "WPF leak analyzer /
  `WPFxxx` codes" to "subscription / lifetime analysis + a WPF *profile* (rule IDs)."
  Keep emitting `OWN001`/`OWN014`; the `[resource: kind]` tag already names the
  sub-domain.
- **Later (only on demand):** mint `SUB`/`TMR` as first-class diagnostic codes *if*
  the `[resource]` tag ever can't carry a distinction we need. Renaming shipped
  behaviour costs goldens, `corpus/wpf/`, `tests/test_wpf.py` — and the codes users
  see are already neutral, so there is no rush.
- **Don't:** put any WPF knowledge into the core, or split `event += without -=` out
  of `OWN001`. It *is* `OWN001`. WPF is a lens, not the lesson.

**Verdict:** the core is already domain-neutral and correct. The work is (1) stop
the *docs* over-claiming WPF, and (2) make `OWN001`'s severity honest about source
lifetime, with the WPF/region profile as the evidence that escalates a hedge to a
verdict.
