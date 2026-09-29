// P-037-X Stage 7 hostile control X7-C1 (frozen in paper-eval/p037-max/stage7-cross-language-prereg-v1.json):
// e1's shape with an OPAQUE guard argument. G-A1 joins: the collapse (may) and the honest
// OWN051 advisory in both arms; never a fabricated release.
interface Res { close(): void; }
declare function open(path: string): Res;
declare function cond(): boolean;

function closeUnlessKept(r: Res, keep: boolean): void {
  if (!keep) {
    r.close();
  }
}

export function maybe(path: string): number {
  const r = open(path);
  closeUnlessKept(r, cond());
  return 1;
}
