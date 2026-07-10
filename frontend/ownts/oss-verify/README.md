# OwnTS OSS true-positive — runtime confirmation

Independent, runtime confirmation that the two **true positives** from the OwnTS OSS
benchmark ([`docs/notes/ownts-oss-benchmark.md`](../../../docs/notes/ownts-oss-benchmark.md),
"First confirmed TRUE positive") are *real* listener leaks — not the analyzer merely
agreeing with itself.

The analyzer flags these shapes **statically** already
([`examples/EffectFunctionCallback.tsx`](../examples/EffectFunctionCallback.tsx) pins
the capture-mismatch). This project is the other half: it **executes** the reduced
shapes in a real DOM and observes that the effect's own cleanup fails to remove the
listener. Each leak case is paired with a **control** that cleans up correctly and
must go silent, so a passing leak assertion can't be a harness artefact.

## The two findings

| # | Package | Site | Upstream file sha256 | Bug class |
|---|---------|------|----------------------|-----------|
| 1 | `react-scroll-to-bottom@4.2.0` | `lib/esm/ScrollToBottom/Composer.js:574` (add) / `:579` (remove) | `114886d7…efe16` | capture-flag mismatch: added `{ capture: true }`, removed with default `false` |
| 2 | `@reactuses/core@6.4.0` (hook `useMousePressed`) | `dist/index.mjs:2830/2835` (add) / `:2846/2851` (remove); `listenerOptions$2` at `:2809` | `4e47dc7a…6b9c` | fresh function identity: `onPressed = t => () => {…}`, so `onPressed('mouse')` is a new fn at add and again at remove |

Both `removeEventListener` calls therefore never match what `addEventListener`
registered, and a listener piles up on every effect re-run / `target` change.

> **Note on case 2 — it is identity, not the dropped option.** The published add
> passes `listenerOptions$2 = { passive: true }` and the remove omits it, so it may
> look like an option-drop leak. It is not: a listener's removal key is `(type,
> callback, capture)` — `passive` is not part of it, and no `capture` is set (false
> on both sides). The sole cause is the fresh function identity; the case-2 control
> adds *with* `{ passive: true }` and removes *without* it and still goes clean,
> isolating the option-drop as a red herring.

## Run

```bash
cd frontend/ownts/oss-verify
npm ci        # or: npm install
npm test      # node --test, exits non-zero if any leak/control assertion fails
```

Expected: `# pass 5  # fail 0` — two leak proofs, two controls, one root-cause identity check.

## What "confirmed" rests on

- **jsdom** is the committed DOM engine (hermetic, no browser binary — runs in CI).
- The same five assertions were **cross-checked in real Chromium** (Playwright,
  pre-installed headless build). Identical result:

  | check | jsdom | Chromium |
  |-------|:-----:|:--------:|
  | case 1 buggy cleanup — listener still fires | 1 | 1 |
  | case 1 correct cleanup — silent | 0 | 0 |
  | case 2 buggy cleanup — listener still fires | 1 | 1 |
  | case 2 correct cleanup — silent | 0 | 0 |

  So the leak is a property of the DOM spec (capture flag and function identity are
  both part of a listener's removal key), reproduced identically by both engines —
  not a jsdom quirk.

## Provenance / no vendored source

Per the repo policy (`.gitignore`: *"Never commit other projects' code"*), the
register/cleanup helpers in the test are **minimal reduced cases authored here**, not
copies of the upstream source. The table above pins each to `pkg@version : file :
line` plus the upstream file sha256, so the shapes can be re-derived from a fresh
`npm pack react-scroll-to-bottom@4.2.0 @reactuses/core@6.4.0` and diffed if either
package is republished.
