// P-037-X Group E: the safe twin of e1. `keep: false` reaches the close on the
// helper's only path, so the obligation moves into the helper: no finding.
interface Res { close(): void; }
declare function open(path: string): Res;

function closeUnlessKept(r: Res, keep: boolean): void {
  if (!keep) {
    r.close();
  }
}

export function fine(path: string): number {
  const r = open(path);
  closeUnlessKept(r, false);
  return 1;
}
