# OwnTS real-world benchmark — the false-positive reckoning

A field note answering the gating question P-020 set for the OwnTS spike: *does it
find real `useEffect` leaks in real OSS with low false positives?* Short answer for
the first run: **no — 28/28 findings were false positives.** This note records the
corpus, the result, and the prioritized false-positive (FP) catalog the run
produced, plus what was done about it.

## Method

- **Corpus.** Real, published React hook libraries pulled from **npm** (the
  session's egress policy blocks `github.com`, so a raw-source clone was not
  possible; npm registry is allowed). Limited to packages whose published build is
  **modern arrow-function ESM**, which the source-tuned spike parses as-is:
  - `@mantine/hooks` 9.4.0
  - `@react-hookz/web` 25.2.0
  - `@uidotdev/usehooks` 2.4.1
  - `usehooks-ts` 3.1.1
- **Caveat.** `ahooks` and `react-use` were pulled too but ship **ES5
  (`function(){}`) output**, which the spike (tuned for arrow `() =>` callbacks and
  `return () =>` cleanups) does not parse — a separate parser-coverage gap, excluded
  from the FP analysis rather than counted as analyzer FPs.
- **Scale.** ~108 `useEffect` calls across 81 files.
- **Run.** Each file → `ownts.extract` + `ownts.extract_effects` → `check_facts`;
  findings collected and then **triaged by reading the actual source** around each.

## Result (baseline — before this PR's fixes)

| Code | Findings | True positive | False positive |
|------|---------:|--------------:|---------------:|
| `OWN001` | 28 | 0 | **28** |
| `EFF001` | 0 | — | — |
| **Total** | **28** | **0** | **28 (100%)** |

Zero real leaks, zero effect storms, 28 false positives. These are well-maintained
libraries that *do* clean up — just with patterns the synthetic-fixture-tuned spike
did not model.

## The FP catalog (what real code does that the spike missed)

Ordered by frequency; each is a frontend (not core) limitation.

1. **AbortController `{ signal }`** — listeners added with a `signal` option and torn
   down by `controller.abort()` in cleanup (abort removes every signal-bound
   listener at once). The spike had no model for it. *(mantine `use-floating-window`,
   7 findings.)*
2. **Handle stored in a ref / pre-declared `let`** — `timeoutRef.current =
   setTimeout(...)`, `let i; … i = setInterval(...)`. `_lhs_token` only recognized a
   same-statement `const/let/var NAME =`, so the handle was "uncapturable" and the
   matching `clearTimeout(ref.current)` never matched. *(debounced-value, use-idle,
   uidotdev, useVibrate.)*
3. **Cleanup `return` from a nested block** — the `return () => …` lives inside an
   `if` / `try` / `.then()` within the effect. `_cleanup_span` only accepted a return
   at the effect body's own brace depth (1), so a depth-2 cleanup was invisible and
   every resource read as un-released. *(use-media-query, use-scroller, useVibrate.)*
4. **Aliased receiver** — `b.addEventListener(...)` in a `.then(b => …)` callback,
   torn down by `battery.removeEventListener(...)` (same object, different
   identifier). The full-key match compares the receiver string, so `b ≠ battery`.
   *(uidotdev `useBattery`, 4 findings.)*
5. **Cleanup via a named function or a method** — `return cancel`, `ro.unsubscribe`,
   `resizeObserver.disconnect()`. The matcher could not follow a function reference
   or a bare-statement subscribe. *(react-hookz `useResizeObserver`, debounced-value.)*
6. **One-shot `setTimeout`** with no captured handle — fires once and is gone, not a
   retained resource, but flagged like an un-cleared `setInterval`. *(use-focus-trap.)*

## Verdict

The spike was **not alpha-ready** on idiomatic modern hook code: ~100% FP. This is
the honest "value, not form" check the consolidation note asked for. The catalog is
the payoff — a concrete, prioritized list of what to model next, every item a small
frontend extension.

## What this PR changed (after)

This PR teaches the **frontend** (not the core) to recognize the *provable* cleanup
patterns — those where the teardown is visible in the effect — and leaves the
genuinely-hard ones documented rather than guessed. Implemented:

- **AbortController `{ signal }`** (#1): a signal-bound listener is released by a
  `controller.abort()` in cleanup.
- **Ref / pre-declared handle** (#2): `_lhs_token` now also recognizes
  `ref.current = setTimeout(...)` and `let i; i = setInterval(...)`, so the matching
  `clearTimeout(ref.current)` / `clearInterval(i)` lands.
- **Nested-block cleanup** (#3): `_cleanup_span` switched from brace-depth to
  **function-depth**, so a `return () => …` inside an `if`/`try`/`.then()` is the
  effect's cleanup, while a `return` inside a nested callback still is not.
- **Observer subscribe/unsubscribe** (part of #5): a bare `recv.subscribe(...)` is
  released by `recv.unsubscribe(...)` / `recv.disconnect()` on the same receiver.

Pinned by `frontend/ownts/examples/EffectRealWorld.tsx` (distilled from the OSS
cases) + a CI step; `Dashboard`/`EffectEdges` still flag real leaks, proving the
fixes do not over-suppress.

### Result (after)

| | Findings | Confirmed leaks | False positives |
|---|---:|---:|---:|
| **Baseline** | 28 | 0 | 28 |
| **After** | **11** | 0 | 9 FP + 2 borderline |

**17 false positives eliminated** (61%); correctly-silent effects rose from
**80/108 → 97/108** specificity. Still zero confirmed leaks — these are
well-maintained libraries, so that is the *expected* honest outcome, not a miss.

### Residual (deliberately not fixed — they would require guessing)

- **Aliased receiver** (#4): `b.addEventListener(...)` torn down by
  `battery.removeEventListener(...)` (same object, different identifier). Needs alias
  analysis. *(uidotdev `useBattery`, 4.)*
- **Cross-effect / named-helper cleanup** (#5): the teardown is a `cancel()` /
  `removeEventListeners()` helper, often called from a *different* effect. Following
  it is interprocedural — out of scope for a narrow frontend. *(mantine
  `use-debounced-value` 2, uidotdev `useScript` 2.)*
- **One-shot `setTimeout`** (#6): an uncaptured `setTimeout` fires once and frees
  itself; flagging it like a repeating `setInterval` is the conservative-but-noisy
  call. Left as-is rather than silently suppressed (which could hide a real
  re-render pileup). *(mantine `use-focus-trap`, 1.)*
- **Borderline**: a listener intentionally left on a *cached* shared `<script>` node
  (`usehooks-ts` `useScript`, 2) — defensible either way; the spike correctly
  observes "never removed."

The honest takeaway: OwnTS is now quiet on idiomatic cleanup, with its remaining
false alarms confined to four named, understood patterns — a real step toward the
"low false positives" bar P-020 set, without a single guessed release.

## First confirmed TRUE positive — a real hanging effect

Hook *libraries* clean up by design, so the honest hunt for a real leak moved to
*application-shaped* component code. In **`react-scroll-to-bottom@4.2.0`**
(`ScrollToBottom/Composer.js:574`):

```js
// as published — transpiled ES5: a `function () {}` cleanup, not an arrow
target.addEventListener('focus', handleFocus, { capture: true, passive: true });
return function () {
  return target.removeEventListener('focus', handleFocus);       // default capture (false)
};
```

`removeEventListener` must match the capture flag; `capture: true` is added but the
removal uses the default `false`, so the listener is **never removed** — a new one
piles up every time `target` changes. (The cleanup is an ES5 `function () {}`, so it
is only reachable after the parser change below; the bug is then the capture-mismatch
class the listener-key matching (P-148/#145) models, not a missing cleanup.) A second
real one:
**`@reactuses/core@6.4.0`** passes `onPressed('mouse')` (a freshly *returned*
function) to both add and remove, so the drag/touch listeners can never be removed.

## ES5 (`function () {}`) build coverage

The benchmark above is arrow-ESM only. To reach the capture-mismatch bug for the
*right* reason — and to widen the corpus to transpiled output (`ahooks`,
`react-use`, and the Composer file above ship ES5 `function(){}`) — the frontend now
parses `function` callbacks and `return function () {}` cleanups
(`EffectFunctionCallback.tsx` pins it: a matched ES5 cleanup is silent, the
capture-mismatch is the one finding). The ES5 corpus (`ahooks` + `react-use`, ~93
`useEffect`) then yields 11 findings, again triaged as FPs from the known patterns
plus one new transpilation artifact: **optional-chaining desugaring**
(`ref.current?.removeEventListener` → `(_a = ref.current) ? … : _a.removeEventListener`)
makes the cleanup receiver a temp `_a ≠ ref.current`, which the exact-receiver match
rejects. Documented as residual; alias-resolving `_a` back to `ref.current` is the
next increment.

### Reproduce

```bash
# (egress to npm only; github.com is blocked in this environment)
# versions pinned to the exact builds benchmarked above, so reruns are reproducible
npm pack @mantine/hooks@9.4.0 @react-hookz/web@25.2.0 \
         @uidotdev/usehooks@2.4.1 usehooks-ts@3.1.1
# extract each tarball, then run ownts.extract + extract_effects + check_facts
# over every *.js/*.mjs (skip *.d.ts); triage each finding against the source.
```

### Soundness of the new matchers

The broadened release matchers stay **fail-closed** — a release-shaped cleanup that
does not actually release *this* resource still reports the leak, pinned by
`EffectLeakControl.tsx`: a listener bound to `c1.signal` torn down by `c2.abort()`,
a `ro.subscribe(a, h)` "released" by `ro.unsubscribe(b, h)`, and a cleanup returned
only under `if (enabled)` over an unconditional `setInterval` — all three remain
`OWN001`. The signal is tied to its controller, the observer to its argument list,
and a conditional cleanup only releases acquires it dominates (co-guarded in the
same block).
