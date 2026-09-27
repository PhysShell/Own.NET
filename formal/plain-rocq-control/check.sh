#!/usr/bin/env bash
# Plain-Rocq control (#367): regenerate the Rust tables with the UNCHANGED
# MathComp-spike exporter, retarget its two import lines, check every proof.
# Needs cargo and Rocq 9.2 + rocq-stdlib 9.2 (no MathComp) on PATH.
set -euo pipefail
cd "$(dirname "$0")"
W=(-w -notation-for-abbreviation)
cargo run -q --manifest-path ../mathcomp-spike/export/Cargo.toml \
  | sed -e 's/^From mathcomp Require Import boot\.$/From Stdlib Require Import List./' \
        -e 's/^From P037Spike Require Import P037\.$/From PlainSpike Require Import P037./' \
  > theories/RustTables.v.new
if ! cmp -s theories/RustTables.v.new theories/RustTables.v 2>/dev/null; then
  echo "RustTables.v regenerated from formal/p037-kernel." >&2
fi
mv theories/RustTables.v.new theories/RustTables.v
for f in Lfp P037 RustTables Correspondence; do
  t0=$(date +%s.%N)
  rocq compile "${W[@]}" -Q theories PlainSpike "theories/$f.v" > /dev/null
  printf '  %-18s %.1fs\n' "$f.v" "$(echo "$(date +%s.%N) - $t0" | bc)"
done
rocq compile "${W[@]}" -Q theories PlainSpike theories/Audit.v | grep -E "Closed|Axioms|^[A-Za-z_]+ :" || true
