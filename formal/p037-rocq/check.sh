#!/usr/bin/env bash
# formal/p037-rocq: regenerate RustTables.v from the REAL formal/p037-kernel
# via export/ (moved from formal/mathcomp-spike/export, PR #367), then check
# every proof. Needs cargo and Rocq 9.2 + rocq-stdlib 9.2 (no MathComp) on
# PATH.
#
# A stale committed theories/RustTables.v FAILS this check instead of being
# silently overwritten. Regenerate it explicitly with:
#   cargo run -q --manifest-path export/Cargo.toml > theories/RustTables.v
set -euo pipefail
cd "$(dirname "$0")"
W=(-w -notation-for-abbreviation)

fresh=$(mktemp)
trap 'rm -f "$fresh"' EXIT
cargo run -q --manifest-path export/Cargo.toml > "$fresh"

if ! cmp -s "$fresh" theories/RustTables.v; then
  echo "FAIL: theories/RustTables.v is stale relative to formal/p037-kernel." >&2
  echo "Regenerate with:" >&2
  echo "  cargo run -q --manifest-path export/Cargo.toml > theories/RustTables.v" >&2
  exit 1
fi

for f in Lfp P037 RustTables Correspondence Election; do
  t0=$(date +%s.%N)
  rocq compile "${W[@]}" -Q theories PlainSpike "theories/$f.v" > /dev/null
  printf '  %-18s %.1fs\n' "$f.v" "$(echo "$(date +%s.%N) - $t0" | bc)"
done
echo "--- Audit.v ---"
rocq compile "${W[@]}" -Q theories PlainSpike theories/Audit.v | grep -E "Closed|Axioms|^[A-Za-z_]+ :" || true
echo "--- ElectionAudit.v ---"
rocq compile "${W[@]}" -Q theories PlainSpike theories/ElectionAudit.v | grep -E "Closed|Axioms|^[A-Za-z_]+ :" || true
