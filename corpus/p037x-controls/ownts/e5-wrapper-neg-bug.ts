// P-037-X Group E: a wrapper NEGATES its flag on the edge (P-037 §8 row 8, `neg` edge).
// `outer(r, false)` becomes `inner(r, true)`, which never closes: OWN001.
interface Res { close(): void; }
declare function open(path: string): Res;

function inner(r: Res, keep: boolean): void {
  if (!keep) {
    r.close();
  }
}

function outer(r: Res, stop: boolean): void {
  inner(r, !stop);
}

export function leak(path: string): number {
  const r = open(path);
  outer(r, false);
  return 1;
}
