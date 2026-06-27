# P-020 — OwnTS React effects profile (`Own.React`) — the effect-storm angle

- **Status:** draft — **experiment / proposal, explicitly not mainline.** A
  marketing-shaped spike under the OwnTS frontend, on the record so the framing is
  honest before any code.
- **Depends on:** [P-017](P-017-multi-stack-frontends.md) (the OwnTS frontend &
  confidence tiers that this profile feeds), `spec/OwnCore.md` (the acquire/release
  vocabulary), [P-004](P-004-wpf-lifetime-profile.md) (WPF — the same lifecycle
  model in a different skin).

## The seam this fits

[P-017](P-017-multi-stack-frontends.md) splits two axes: the **OwnTS frontend**
(what parses JS/TS and emits OwnIR) vs a **platform profile** (the lifetime/effect
facts a domain needs). This proposal is the second kind: **`Own.React`**, the
effect/cleanup profile the OwnTS frontend feeds the core — exactly as WPF is a
profile for the .NET side. P-017 owns the frontend mechanics and the
`OWNTS001–005` authoring rules; P-020 specifies the `Own.React` **EFF** catalog and
the effect-storm analysis behind it.

## Motivation — not all lifecycle bugs leak memory; some leak requests

The originating hook is the Cloudflare dashboard/API outage of **12 Sep 2025**,
described (in a Panto AI DEV post, 16 Sep 2025) as a "self-DDoS": a React dashboard
update created a runaway loop of redundant API requests, traced to a `useEffect`
whose dependency object was re-created on every render, re-running the effect each
time.

**Read the source honestly.** That post is a *vendor/marketing* text, not a neutral
postmortem — it closes by suggesting an AI reviewer like Panto would have flagged
it. So the case is a great *PR angle* and a poor *proof*. We do **not** claim
"Own.NET would have prevented the Cloudflare outage" — that is the startup classic
("we can't catch this bug class yet, but we'd already have saved the internet").
The honest, and stronger, framing:

> Cloudflare-style outages show that lifecycle bugs are not just memory bugs.
> A single unstable UI effect can become a control-plane incident. Own models
> subscriptions, timers, resources, and effects as explicit contracts, so teams can
> catch lifecycle mistakes before they become production loops.

The one-liner: **"Not all lifecycle bugs leak memory. Some leak requests."**

This matters to the project because React `useEffect` is the *same animal* the core
already models for .NET — `event += / -=`, `Subscribe()/Dispose`, timers,
lifetimes — wearing JSX:

```tsx
useEffect(() => { subscribe(); return () => unsubscribe(); }, [deps]); // cleanup contract
useEffect(() => { fetchTenantData(filters); }, [filters]);            // effect-storm if `filters` is unstable
```

## The `Own.React` EFF catalog

Profile catalog IDs (like `WPFxxx` — they live in the catalog and map to **core**
verdicts/labels; the emitter stays core `OWN` codes + a `[profile: react]` /
`[resource: …]` tag, per the consolidation discipline):

| EFF | Pattern | Maps to | Tier |
|-----|---------|---------|------|
| `EFF001` | unstable dependency object re-runs the effect, **and** the effect does external IO (request storm) | **new** stability analysis (see below) | effect-storm |
| `EFF002` | effect performs a network request with no stable guard | **new** stability analysis | effect-storm |
| `EFF003` | effect subscribes without a cleanup `return` | `OWN001` (acquire w/o release) | leak |
| `EFF004` | `setInterval`/`setTimeout` in an effect without cleanup | `OWN001` | leak |
| `EFF005` | `AbortController` created but never `abort()`ed | `OWN001` | leak |

**Honest split.** `EFF003/004/005` *are* the existing acquire→release/`OWN001`
model — the same fact shape P-001 already proved, just emitted by the OwnTS
frontend. `EFF001/002` (the actual Cloudflare shape) are **not** an acquire/release
leak; they are a *new* analysis dimension — **dependency-identity stability** →
effect re-trigger → IO storm. The core does not model that today. This proposal
names it as the new capability it would require, rather than pretending the leak
checker already covers it (see Open questions).

## The spike (one rule, end-to-end, not a TypeScript analyzer)

Build **`EFF001` only**, in TS mode, as a small experiment — *not* a general
TypeScript effect analyzer.

Bad (flagged):

```tsx
function Dashboard({ tenantId }: Props) {
  const filters = { tenantId };            // new object identity every render
  useEffect(() => {
    fetch(`/api/tenant/${filters.tenantId}`);
  }, [filters]);                            // → effect re-runs every render
}
```

```text
EFF001: unstable object dependency 'filters' causes the effect to re-run on every
render. The effect performs network IO; this can create a request storm.
```

OK (silent):

```tsx
function Dashboard({ tenantId }: Props) {
  useEffect(() => { fetch(`/api/tenant/${tenantId}`); }, [tenantId]); // stable primitive dep
}
// — or — const filters = useMemo(() => ({ tenantId }), [tenantId]); ... }, [filters]);
```

The article line that pays for the spike: *"The same OwnIR idea behind WPF
subscription leaks can model React effect storms."*

## Positioning — deterministic contract checker, not another AI reviewer

The competitive note that frames this whole direction lives at the hub
([ROADMAP — Positioning against the competition](../ROADMAP.md#positioning-against-the-competition-not-another-sast)).
The React-specific edge over a Panto-style AI reviewer:

| AI reviewer | Own / OwnTS |
|-------------|-------------|
| *maybe* flags a suspicious pattern | explicit resource/effect/lifetime **facts** |
| natural-language, nondeterministic | deterministic rule, reproducible **SARIF** |
| no suppression/spec contract | suppression + spec mechanism, cross-language model |

We do **not** fight AI reviewers head-on. The grown-up line is: *an LLM may
**propose** a suspicious lifecycle contract; Own **verifies** it deterministically.*

## Non-goals

- **Not a TypeScript effect/dataflow analyzer.** One rule (`EFF001`), TS mode,
  spike only. General closure/render-dataflow stays out (same narrow-frontend
  discipline as the C# side).
- **No "we'd have saved Cloudflare" claim**, in README, talk, or PR. The hook is
  "lifecycle bugs aren't only memory bugs," never a counterfactual rescue.
- **Not mainline.** This rides as an experiment/proposal until the .NET surface is
  a tasty alpha and the spike demonstrably finds real effect storms in real OSS
  dashboards with low false positives.
- **No second checker.** `Own.React` emits OwnIR facts (`EFF003/004/005`) or routes
  through the new stability analysis (`EFF001/002`); the Python core stays the one
  checker.

## What a Cloudflare-type buyer actually needs (so we don't ship "buy our idea")

A real org evaluates the *demo that catches the bug class*, not the DSL. The bar:

1. a reproducible minimal example of the class; 2. the rule catches it with low
false positives; 3. SARIF / GitHub annotation; 4. CI integration; 5. a suppression
mechanism; 6. a plain "why this becomes a request storm" explanation; 7. a
benchmark — *finds N real issues in OSS dashboards*. Items 3–5 the project already
has on the .NET side (P-013/P-015); 1/2/6/7 are this proposal's actual work.

## Open questions

1. **The new analysis for `EFF001/002`.** Detecting "dependency identity is unstable
   across renders" needs render-scope object-literal/identity reasoning the core
   has no model for. Is that a small, self-contained *stability* fact
   (`unstable(dep, effect)`) the OwnTS frontend can emit and the core treat like an
   acquire-site, or a genuinely new core analysis? This is the gating question — do
   not let `EFF001` masquerade as an `OWN001` leak.
2. **Confidence tier.** `EFF001` clearly wants TS-mode type info (is the dep an
   object literal? does the body do IO?). What, if anything, survives into JS mode
   (P-017's heuristic tier) as a warning?
3. **Overlap with P-017's `OWNTS003/004`.** `EFF003/004` restate the cleanup rules
   from the OwnTS authoring surface — keep one canonical home (the `Own.React`
   profile here) and have P-017's ESLint rules reference it, not duplicate the
   semantics.
