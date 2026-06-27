// Real-world cleanup patterns the OSS benchmark (docs/notes/ownts-oss-benchmark.md)
// found the spike was missing — each distilled to a minimal release that the
// frontend must now recognise. Run:
//   python frontend/ownts/ownts.py frontend/ownts/examples/EffectRealWorld.tsx --check
// Expect ZERO findings — every resource here is properly released.
// (The "still leaks" control lives in Dashboard.tsx / EffectEdges.tsx, so this
// fixture also proves the fixes did not over-suppress real leaks.)
import { useEffect, useRef } from "react";

export function RealWorld({ src }: { src: string }) {
  // AbortController: listeners bound to a signal, torn down by controller.abort().
  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    window.addEventListener("mousemove", onMove, { signal });
    window.addEventListener("mouseup", onEnd, { signal });
    return () => controller.abort();
  }, []);

  // Timer handle stored in a ref, cleared inline in cleanup.
  const timeoutRef = useRef(-1);
  useEffect(() => {
    timeoutRef.current = window.setTimeout(() => onReady(), 200);
    return () => window.clearTimeout(timeoutRef.current);
  }, []);

  // Pre-declared `let` handle, assigned then cleared.
  useEffect(() => {
    let interval;
    interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, []);

  // Cleanup returned from a NESTED block (inside `if`) — still the effect's cleanup.
  useEffect(() => {
    if ("matchMedia" in window) {
      const mq = window.matchMedia(src);
      const cb = (e) => onMatch(e.matches);
      mq.addEventListener("change", cb);
      return () => mq.removeEventListener("change", cb);
    }
  }, [src]);

  // Bare observer.subscribe(...) released by observer.unsubscribe(...) on the same receiver.
  useEffect(() => {
    ro.subscribe(target, handler);
    return () => ro.unsubscribe(target, handler);
  }, []);

  return <div>real world</div>;
}
