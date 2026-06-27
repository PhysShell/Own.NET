# OwnTS — React `useEffect` frontend spike (`Own.React`)

The TypeScript sibling of the [Roslyn C# extractor](../roslyn/). It scans a
React `.tsx`, emits **OwnIR** facts, and lets the **existing** Python core
(`python -m ownlang ownir`) flag the leak. Same seam, same checker, different
skin — a `useEffect` acquire without a cleanup `return` is the core's `OWN001`,
exactly as a C# `event +=` without `-=` is.

> The same OwnIR idea behind WPF subscription leaks can model React effect storms.

This is a **spike**, per [P-020](../../docs/proposals/P-020-ownts-react-effects.md)
— deliberately *not* a TypeScript analyzer. Extraction is heuristic (brace
matching + cleanup-verb detection), not a real TS parse. Its only job is to prove
the seam is cross-language.

## Run it

```bash
# print the OwnIR facts extracted from a .tsx
python frontend/ownts/ownts.py frontend/ownts/examples/Dashboard.tsx

# extract + run straight through the core (the "catch")
python frontend/ownts/ownts.py frontend/ownts/examples/Dashboard.tsx --check

# the EFF001 stability showcase (propagation + the conservative silent cases)
python frontend/ownts/ownts.py frontend/ownts/examples/EffectStorm.tsx --check

# or the real two-step CLI, same as the C# side:
python frontend/ownts/ownts.py frontend/ownts/examples/Dashboard.tsx -o facts.json
python -m ownlang ownir facts.json --format sarif

# pin the spike
python frontend/ownts/test_ownts.py
```

`Dashboard.tsx` drops three `OWN001` leaks **and** one `EFF001` effect storm;
`DashboardClean.tsx` (every acquire has a cleanup `return`, and the unstable dep is
`useMemo`'d) is silent.

```text
Dashboard.tsx:13: error: [OWN001] timer 'setInterval(() =>' ... never stopped ... (leak) [resource: timer]
Dashboard.tsx:21: error: [OWN001] the result of '.subscribe(...)' is ignored ... (leak) [resource: subscription token]
Dashboard.tsx:27: error: [OWN001] event '.addEventListener(...)' ... never unsubscribed ... (leak) [resource: subscription token]
Dashboard.tsx:34: error: [EFF001] effect re-runs on every render: dependency 'filters' is an object literal ... can become a request storm ... [resource: react effect]
```

## What it catches — the honest `Own.React` slice

| EFF | Pattern | OwnIR fact | Core verdict |
|-----|---------|-----------|--------------|
| `EFF004` | `setInterval`/`setTimeout` in an effect, no `clearInterval`/`clearTimeout` cleanup | `resource: timer` | `OWN001` |
| `EFF003` | `X.subscribe(...)` with no `unsubscribe` cleanup | `resource: subscribe` | `OWN001` |
| `EFF003` | `addEventListener` with no `removeEventListener` cleanup | `resource: subscription` | `OWN001` |
| `EFF001` | IO effect with a render-unstable dependency identity | `effects` block | `EFF001` (new core analysis — see below) |

These three **are** the existing acquire→release model, just emitted by an OwnTS
frontend. The core is untouched.

## EFF001 — a real core analysis (not a heuristic, not OWN001)

`EFF001` — the unstable-dependency "effect storm" (the Cloudflare 12-Sep-2025
shape: a `useEffect` whose dep object is re-created each render, re-firing the
effect and storming the API) — **is not an acquire/release leak.** It is a new core
analysis: **dependency-identity stability** (`ownlang/effects.py`), its own core
code like `DI001`, *never* an `OWN001`.

The honest split is preserved end-to-end. The frontend emits only **facts** — for
each `useEffect`, its dep list, whether the body does IO, and a render-scope
**binding table** (what each binding syntactically is: `object`/`array`/`new`,
`memo`/`callback`/`ref`, `ident` derivation + the names it references, `call`, …).
It does **not** pre-judge stability. The **core** runs an identity-stability lattice
(`STABLE < UNKNOWN < UNSTABLE`) to a fixpoint over the references and decides:

```text
EFF001 fires  ⟺  the effect does IO  ∧  some dep is *provably* UNSTABLE
```

- object/array literal in render scope → UNSTABLE (fresh identity every render)
- `useMemo`/`useCallback`/`useRef`, prop, primitive → STABLE
- an alias/derivation → the worst of what it references (instability *propagates*)
- an opaque `call(...)` → UNKNOWN → **no finding** (conservative; low false positives)

See `examples/EffectStorm.tsx`: two storms fire (a direct object dep and the alias
that derives from it — `derives from 'filters' ... (via alias -> filters)`), while
the memoised, ref, opaque-call, primitive, and no-IO effects all stay silent.

The one-liner the spike pays for: **"Not all lifecycle bugs leak memory. Some
leak requests."** We make **no** "Own would have prevented the Cloudflare outage"
claim — see P-020's Non-goals.
