// P-037-X Group E: a wrapper forwards its flag unchanged (P-037 §8 row 7, `id` edge).
// `outer(r, true)` selects inner's `no` cell one hop up: OWN001.
interface Res { close(): void; }
declare function open(path: string): Res;

function inner(r: Res, keep: boolean): void {
  if (!keep) {
    r.close();
  }
}

function outer(r: Res, keep: boolean): void {
  inner(r, keep);
}

export function leak(path: string): number {
  const r = open(path);
  outer(r, true);
  return 1;
}
