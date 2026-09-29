// P-037-X Group E (frozen before any TypeScript frontend change).
// The P-037 §8 row-1 shape in TypeScript: the helper closes only when `keep` is false.
// The caller passes `true`, so the resource is never closed: the guarded core must
// select the `no` cell and keep the obligation with the caller (OWN001).
interface Res { close(): void; }
declare function open(path: string): Res;

function closeUnlessKept(r: Res, keep: boolean): void {
  if (!keep) {
    r.close();
  }
}

export function leak(path: string): number {
  const r = open(path);
  closeUnlessKept(r, true);
  return 1;
}
