// False-negative controls for the broadened release matchers (Codex/CodeRabbit):
// each uses a release-shaped cleanup that does NOT actually release THIS resource,
// so it must STILL report a leak. Run:
//   python frontend/ownts/ownts.py frontend/ownts/examples/EffectLeakControl.tsx --check
// Expect exactly four OWN001 findings.
import { useEffect } from "react";

export function LeakControl({ enabled }: { enabled: boolean }) {
  // (1) wrong controller: the listener is bound to c1's signal, but cleanup aborts
  // c2 — the original listener stays live.
  useEffect(() => {
    const c1 = new AbortController();
    const c2 = new AbortController();
    window.addEventListener("scroll", onScroll, { signal: c1.signal });
    return () => c2.abort();
  }, []);

  // (2) mismatched unsubscribe args: subscribed with (a, h), torn down with (b, h)
  // — the (a, h) subscription leaks.
  useEffect(() => {
    ro.subscribe(a, h);
    return () => ro.unsubscribe(b, h);
  }, []);

  // (3) conditional cleanup: the timer is created unconditionally, but the cleanup
  // is only returned when `enabled` — the !enabled path leaks.
  useEffect(() => {
    const id = setInterval(tick, 1000);
    if (enabled) return () => clearInterval(id);
  }, [enabled]);

  // (4) async effect: React receives a Promise and never runs the returned
  // function as cleanup, so the listener leaks despite the release-shaped return.
  useEffect(async () => {
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  // (5) async ES5 effect: same async suppression, but the transpiled
  // `async function () { … }` shape — React still ignores the returned
  // `function () {}` cleanup, so the listener leaks.
  useEffect(async function () {
    window.addEventListener("online", onOnline);
    return function () {
      window.removeEventListener("online", onOnline);
    };
  }, []);

  return <div>leak control</div>;
}
