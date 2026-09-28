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
  rocq compile "${W[@]}" -Q theories PlainSpike "theories/$f.v" > /dev/null
  echo "  $f.v compiled"
done

# The assumptions audit fails closed: a failed compile, a missing "Closed
# under the global context" line, or any "Axioms:" line are hard failures,
# never just displayed and ignored. The exact expected count is pinned per
# file so a silently dropped or silently added Print Assumptions line is
# also caught, not just an outright axiom.
check_audit() {
  local file="$1" want="$2" out closed axioms
  out=$(mktemp)
  if ! rocq compile "${W[@]}" -Q theories PlainSpike "theories/$file.v" > "$out" 2>&1; then
    echo "FAIL: $file.v failed to compile:" >&2
    cat "$out" >&2
    rm -f "$out"
    return 1
  fi
  cat "$out"
  closed=$(grep -c "^Closed under the global context$" "$out" || true)
  axioms=$(grep -c "^Axioms:" "$out" || true)
  rm -f "$out"
  if [ "$axioms" -ne 0 ]; then
    echo "FAIL: $file.v reports $axioms axiom-dependent result(s) -- expected none." >&2
    return 1
  fi
  if [ "$closed" -ne "$want" ]; then
    echo "FAIL: $file.v reports $closed \"Closed under the global context\" result(s)," \
         "expected exactly $want." >&2
    return 1
  fi
}

echo "--- Audit.v ---"
check_audit Audit 10
echo "--- ElectionAudit.v ---"
check_audit ElectionAudit 6
