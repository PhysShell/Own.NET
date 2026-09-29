// P-037-X Group E: the safe twin of e3. `outer(r, false)` selects inner's consume cell: clean.
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

export function fine(path: string): number {
  const r = open(path);
  outer(r, false);
  return 1;
}
