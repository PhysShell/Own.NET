// EFF001 showcase — the core's dependency-identity *stability* analysis, not a
// leak. Only the IO effects whose dep is PROVABLY unstable fire; memoised,
// primitive, opaque-call and no-IO cases stay silent (low false positives).
//
//   python frontend/ownts/ownts.py frontend/ownts/examples/EffectStorm.tsx --check
//
// Expect exactly two EFF001 findings: the direct object dep, and the alias that
// derives from it.
import { useEffect, useMemo, useRef } from "react";

export function StormBoard({ tenantId }: { tenantId: string }) {
  // (1) FIRES — fresh object identity every render + IO.
  const filters = { tenantId };
  useEffect(() => {
    fetch(`/api/tenant/${filters.tenantId}`);
  }, [filters]);

  // (2) FIRES — `alias` derives from the unstable `filters`; instability propagates.
  const alias = filters;
  useEffect(() => {
    fetch(`/api/alias/${alias.tenantId}`);
  }, [alias]);

  // (3) SILENT — useMemo gives a stable identity across renders.
  const stable = useMemo(() => ({ tenantId }), [tenantId]);
  useEffect(() => {
    fetch(`/api/stable/${stable.tenantId}`);
  }, [stable]);

  // (4) SILENT — useRef identity is stable.
  const box = useRef({ tenantId });
  useEffect(() => {
    fetch(`/api/ref/${box.current.tenantId}`);
  }, [box]);

  // (5) SILENT — opaque call: the core stays conservative (UNKNOWN, no finding).
  const computed = makeFilters(tenantId);
  useEffect(() => {
    fetch(`/api/computed/${computed.tenantId}`);
  }, [computed]);

  // (6) SILENT — primitive dependency has a stable value identity.
  useEffect(() => {
    fetch(`/api/primitive/${tenantId}`);
  }, [tenantId]);

  // (7) SILENT — unstable dep but NO IO: re-running is cheap, not a storm.
  const opts = { verbose: true };
  useEffect(() => {
    console.log(opts.verbose);
  }, [opts]);

  return <div>storm board</div>;
}
