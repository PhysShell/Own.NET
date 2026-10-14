#!/usr/bin/env bash
# Regenerate the Rust tables, then check every proof. Needs cargo and a
# Rocq 9.2 + MathComp 2.6 (boot) switch on PATH (see README.md).
set -euo pipefail
cd "$(dirname "$0")"
W=(-w -notation-overridden -w -notation-for-abbreviation -w -redundant-canonical-projection)
cargo run -q --manifest-path export/Cargo.toml > theories/RustTables.v.new
if ! cmp -s theories/RustTables.v.new theories/RustTables.v; then
  echo "RustTables.v is stale w.r.t. formal/p037-kernel: regenerated; re-checking." >&2
fi
mv theories/RustTables.v.new theories/RustTables.v
for f in Lfp P037 RustTables Correspondence OrderProbe; do
  t0=$(date +%s.%N)
  rocq compile "${W[@]}" -Q theories P037Spike "theories/$f.v" > /dev/null
  printf '  %-18s %.1fs\n' "$f.v" "$(echo "$(date +%s.%N) - $t0" | bc)"
done
rocq compile "${W[@]}" -Q theories P037Spike theories/Audit.v | grep -E "Closed|Axioms|^[A-Za-z_]+ :" || true
