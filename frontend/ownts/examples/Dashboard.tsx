// Leaky dashboard — three useEffect acquires with NO cleanup return.
// Each is the React skin of the same acquire->release contract the .NET core
// already checks (timer / subscription token). Run:
//
//   python frontend/ownts/ownts.py frontend/ownts/examples/Dashboard.tsx --check
//
// Expect three OWN001 findings (EFF004 timer, EFF003 subscribe, EFF003 listener).
import { useEffect } from "react";

export function Dashboard({ tenantId }: { tenantId: string }) {
  // EFF004 — interval started, never cleared: the timer keeps the component alive.
  useEffect(() => {
    const id = setInterval(() => {
      fetch(`/api/tenant/${tenantId}/metrics`);
    }, 1000);
    // no `return () => clearInterval(id)` — leak
  }, [tenantId]);

  // EFF003 — observable subscription whose teardown is never returned.
  useEffect(() => {
    bus.subscribe((msg) => console.log(msg));
    // no `return () => sub.unsubscribe()` — leak
  }, []);

  // EFF003 — DOM listener added, never removed.
  useEffect(() => {
    window.addEventListener("resize", onResize);
    // no `return () => window.removeEventListener("resize", onResize)` — leak
  }, []);

  // EFF001 (frontend heuristic only — NOT a core OWN001): `filters` is a fresh
  // object identity every render, and the effect does IO -> request storm.
  const filters = { tenantId };
  useEffect(() => {
    fetch(`/api/tenant/${filters.tenantId}`);
  }, [filters]);

  return <div>dashboard</div>;
}
