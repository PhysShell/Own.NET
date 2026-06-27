// Parser-hardening cases (CodeRabbit): string literals must not truncate bodies or
// split deps, deps brackets nest, and a listener is released only by a matching
// target+handler+options removeEventListener. Run:
//   python frontend/ownts/ownts.py frontend/ownts/examples/EffectHardening.tsx --check
// Expect exactly: OWN001 (the options-dropped listener) + EFF001 (the object dep).
import { useEffect } from "react";

export function Hardening({ id }: { id: string }) {
  // A string with commas and braces must not truncate the body or split the deps;
  // the timer IS cleared, so this effect leaks nothing.
  useEffect(() => {
    const t = setInterval(() => fetch("/a,b,{c}"), 1000);
    return () => clearInterval(t);
  }, [id]);

  // Listener added WITH capture, but cleanup drops the option -> different listener,
  // still leaks (one OWN001).
  useEffect(() => {
    window.addEventListener("scroll", onScroll, true);
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Nested-bracket dep parses (`items[0]` stays one entry); the object literal dep
  // is unstable + IO -> exactly one EFF001 (items[0] is not identifier-like: silent).
  const filters = { id };
  useEffect(() => {
    fetch("/x");
  }, [filters, items[0]]);

  return <div>hardening</div>;
}
