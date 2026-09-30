// resource-effects Stage 7 seam twin: the same shape, destroyed. Truth: no leak.
interface Key {
  destroy(): void;
  export(): string;
}
declare function createKey(): Key;

export function safe(): void {
  const k = createKey();
  k.destroy();
}
