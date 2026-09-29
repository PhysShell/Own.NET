// P-037-X Group E: the safe twin of e5. `outer(r, true)` becomes `inner(r, false)`: closed, clean.
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

export function fine(path: string): number {
  const r = open(path);
  outer(r, true);
  return 1;
}
