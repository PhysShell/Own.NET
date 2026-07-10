// Runtime ground-truth confirmation for the two OwnTS OSS *true positives*
// recorded in docs/notes/ownts-oss-benchmark.md ("First confirmed TRUE positive").
//
// The analyzer already flags these shapes statically (see
// frontend/ownts/examples/EffectFunctionCallback.tsx for the capture-mismatch pin).
// This test is the INDEPENDENT half: it proves the flagged shapes genuinely leak a
// listener when executed in a real DOM — so the "true positive" label rests on
// observed behaviour, not on the analyzer's own say-so.
//
// How it proves a leak: register the listener, run the effect's *cleanup*, then
// dispatch the event. If the handler still fires, cleanup failed to remove it — a
// leak. Each case is paired with a CONTROL that cleans up correctly and must go
// silent, so a passing leak assertion cannot be an artefact of the harness.
//
// Repo policy (.gitignore: "Never commit other projects' code") is respected: the
// register/cleanup helpers below are MINIMAL REDUCED CASES authored here, not copies
// of the upstream source. Provenance for each is the pkg@version : file : line and
// the upstream file sha256 recorded in README.md, so a maintainer can re-derive them
// from a fresh `npm pack`.
//
// DOM engine: jsdom (hermetic, no browser binary — CI-friendly). The exact same
// assertions were cross-checked in real Chromium; the numbers are in README.md.

import { test } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

/** A fresh, isolated document + Event constructor per case. */
function dom() {
  const { window } = new JSDOM("<!doctype html><body></body>");
  return { document: window.document, Event: window.Event };
}

// ---------------------------------------------------------------------------
// Case 1 — react-scroll-to-bottom@4.2.0
//   lib/esm/ScrollToBottom/Composer.js:574 (add) / :579 (remove)
//   Bug class: capture-flag mismatch. Added with { capture: true }, removed with
//   the default (capture: false). removeEventListener matches on the capture flag,
//   so the listener is never removed — a new one piles up every time `target`
//   changes. Reduced shape mirrors examples/EffectFunctionCallback.tsx.
// ---------------------------------------------------------------------------
test("RSTB@4.2.0: capture:true add + default-capture remove leaks the listener", () => {
  const { document, Event } = dom();
  const target = document.createElement("div");
  let fired = 0;
  const handleFocus = () => { fired++; };

  // effect body
  target.addEventListener("focus", handleFocus, { capture: true, passive: true });
  // effect cleanup, as published: no options → capture defaults to false
  target.removeEventListener("focus", handleFocus);

  target.dispatchEvent(new Event("focus")); // capture listeners also fire at target
  assert.equal(fired, 1, "listener survived cleanup → leak (expected 1 fire)");
});

test("RSTB control: removing with the matching capture flag is clean", () => {
  const { document, Event } = dom();
  const target = document.createElement("div");
  let fired = 0;
  const handleFocus = () => { fired++; };

  target.addEventListener("focus", handleFocus, { capture: true, passive: true });
  target.removeEventListener("focus", handleFocus, { capture: true }); // the fix

  target.dispatchEvent(new Event("focus"));
  assert.equal(fired, 0, "correct cleanup must remove the listener");
});

// ---------------------------------------------------------------------------
// Case 2 — @reactuses/core@6.4.0
//   dist/index.mjs: add dragstart/touchstart :2830/:2835, remove :2846/:2851
//   Bug class: fresh function identity. onPressed = useCallback(t => () => {…}),
//   so onPressed('mouse') returns a NEW function every call. add registers one
//   instance; cleanup calls onPressed('mouse') AGAIN, producing a different
//   instance that removeEventListener cannot match. The drag/touch listeners are
//   never removed (the sibling onReleased listeners use a stable ref and are fine).
// ---------------------------------------------------------------------------
test("@reactuses/core@6.4.0: onPressed('mouse') returns a fresh fn each call", () => {
  const onPressed = (srcType) => () => { void srcType; };
  assert.notEqual(onPressed("mouse"), onPressed("mouse"),
    "curried onPressed must yield a new identity per call (the root cause)");
});

test("@reactuses/core@6.4.0: add(onPressed('mouse')) + remove(onPressed('mouse')) leaks", () => {
  const { document, Event } = dom();
  const element = document.createElement("div");
  let fired = 0;
  // curried, as published: a new inner fn per invocation
  const onPressed = (srcType) => () => { void srcType; fired++; };

  // effect body — the freshly-returned fn is what gets registered
  element.addEventListener("dragstart", onPressed("mouse"));
  // effect cleanup, as published — a *different* freshly-returned fn
  element.removeEventListener("dragstart", onPressed("mouse"));

  element.dispatchEvent(new Event("dragstart"));
  assert.equal(fired, 1, "listener survived cleanup → leak (expected 1 fire)");
});

test("@reactuses/core control: add & remove the SAME captured fn is clean", () => {
  const { document, Event } = dom();
  const element = document.createElement("div");
  let fired = 0;
  const onPressed = (srcType) => () => { void srcType; fired++; };

  const handler = onPressed("mouse"); // capture once (the fix)
  element.addEventListener("dragstart", handler);
  element.removeEventListener("dragstart", handler);

  element.dispatchEvent(new Event("dragstart"));
  assert.equal(fired, 0, "correct cleanup must remove the listener");
});
