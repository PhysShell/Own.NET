// Edge cases the per-resource + render-scope fixes must get right (Codex/CodeRabbit):
//   python frontend/ownts/ownts.py frontend/ownts/examples/EffectEdges.tsx --check
// Expect exactly ONE finding: OWN001 on the second, uncleared interval. No EFF001.
import { useEffect, useMemo } from "react";

export function EdgeBoard({ id }: { id: string }) {
  // Two timers; only the first is cleared -> the SECOND still leaks. A kind-level
  // "is there any clearInterval?" check would wrongly mark both released.
  useEffect(() => {
    const a = setInterval(pollA, 1000);
    const b = setInterval(pollB, 2000);
    return () => clearInterval(a); // only `a` cleared; `b` leaks (one OWN001)
  }, []);

  // The render-scope dep is memoized (stable). A like-named local INSIDE the effect
  // callback must not shadow it into a false EFF001 storm.
  const filters = useMemo(() => ({ id }), [id]);
  useEffect(() => {
    const filters = { id }; // nested-scope local — NOT the component's render scope
    fetch(`/api/${filters.id}`);
  }, [filters]); // refers to the stable outer (memoized) `filters`

  return <div>edges</div>;
}
