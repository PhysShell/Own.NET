// resource-effects Stage 7 seam twin (pre-registered in Own.NET-paperwork stage7-seam-prereg-v1.json):
// Key is NOT a resource type by the T7 rules (no close()/dispose()); only the effect model makes
// createKey an acquire and destroy() a release. Truth: k is never destroyed (a leak).
interface Key {
  destroy(): void;
  export(): string;
}
declare function createKey(): Key;

export function bug(): void {
  const k = createKey();
  k.export();
}
