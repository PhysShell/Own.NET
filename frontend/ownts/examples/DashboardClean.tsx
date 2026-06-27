// Clean dashboard — every acquire has a matching cleanup return, and the unstable
// dependency is stabilised with useMemo. The extractor sees `released: true` for
// each resource, so the core stays silent (zero findings). Run:
//
//   python frontend/ownts/ownts.py frontend/ownts/examples/DashboardClean.tsx --check
import { useEffect, useMemo } from "react";

export function Dashboard({ tenantId }: { tenantId: string }) {
  useEffect(() => {
    const id = setInterval(() => {
      fetch(`/api/tenant/${tenantId}/metrics`);
    }, 1000);
    return () => clearInterval(id); // released
  }, [tenantId]);

  useEffect(() => {
    const sub = bus.subscribe((msg) => console.log(msg));
    return () => sub.unsubscribe(); // released
  }, []);

  useEffect(() => {
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize); // released
  }, []);

  // stable identity across renders -> no effect storm
  const filters = useMemo(() => ({ tenantId }), [tenantId]);
  useEffect(() => {
    fetch(`/api/tenant/${filters.tenantId}`);
  }, [filters]);

  return <div>dashboard</div>;
}
