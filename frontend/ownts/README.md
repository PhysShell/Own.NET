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

# or the real two-step CLI, same as the C# side:
python frontend/ownts/ownts.py frontend/ownts/examples/Dashboard.tsx -o facts.json
python -m ownlang ownir facts.json --format sarif

# pin the spike
python frontend/ownts/test_ownts.py
```

`Dashboard.tsx` drops three `OWN001` leaks; `DashboardClean.tsx` (every acquire
has a cleanup `return`) is silent.

```
Dashboard.tsx:13: error: [OWN001] timer 'setInterval(() =>' ... never stopped ... (leak) [resource: timer]
Dashboard.tsx:21: error: [OWN001] the result of '.subscribe(...)' is ignored ... (leak) [resource: subscription token]
Dashboard.tsx:27: error: [OWN001] event '.addEventListener(...)' ... never unsubscribed ... (leak) [resource: subscription token]
```

## What it catches — the honest `Own.React` slice

| EFF | Pattern | OwnIR `resource` | Core verdict |
|-----|---------|------------------|--------------|
| `EFF004` | `setInterval`/`setTimeout` in an effect, no `clearInterval`/`clearTimeout` cleanup | `timer` | `OWN001` |
| `EFF003` | `X.subscribe(...)` with no `unsubscribe` cleanup | `subscribe` | `OWN001` |
| `EFF003` | `addEventListener` with no `removeEventListener` cleanup | `subscription` | `OWN001` |

These three **are** the existing acquire→release model, just emitted by an OwnTS
frontend. The core is untouched.

## What it does NOT do (and why that's honest)

`EFF001/002` — the unstable-dependency "effect storm" (the Cloudflare 12-Sep-2025
shape: a `useEffect` whose dep object is re-created each render, re-firing the
effect and storming the API) — **is not an acquire/release leak.** It needs a new
core capability (dependency-identity *stability*), which the core does not have.
Per P-020, `EFF001` must **not** masquerade as `OWN001`.

So the scanner only emits a *frontend-only, clearly-labelled* heuristic note for
`EFF001` candidates on **stderr** — never a core-verified finding:

```
Dashboard.tsx:34: EFF001 (frontend heuristic, NOT core-verified): dependency
'filters' is a fresh object/array identity every render; the effect does IO —
possible request storm. Stabilise with useMemo.
```

The one-liner the spike pays for: **"Not all lifecycle bugs leak memory. Some
leak requests."** We make **no** "Own would have prevented the Cloudflare outage"
claim — see P-020's Non-goals.
