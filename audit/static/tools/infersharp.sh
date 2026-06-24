#!/usr/bin/env bash
#
# Own.NET Audit — Infer# runner (build-required tier).
#
# Infer# analyzes compiled .NET binaries, so it needs a successful build of the
# target with PDBs (`.dll` + `.pdb`) — build-required (Plan.md §3.2/§3.3). For
# net472 on a 12-year-old solution this is the most fragile step, which is why the
# orchestrator treats it as continue-on-error: a failed build yields a partial
# report, not an empty one.
#
# This runs on the LOCAL WINDOWS MACHINE (VS Build Tools + DevExpress). There is no
# CI run of the target.
#
# Usage:
#   infersharp.sh --bin <built output dir with .dll+.pdb> --out <artifacts/own-audit>
#
# Emits: <out>/infersharp.sarif. Exits 3 (NO-TOOL) if the infersharp CLI/container
# is not available.

set -euo pipefail

bin=""
out="artifacts/own-audit"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bin) bin="$2"; shift 2 ;;
    --out) out="$2"; shift 2 ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "infersharp.sh: unknown arg $1" >&2; exit 2 ;;
  esac
done

[[ -n "$bin" ]] || { echo "infersharp.sh: --bin (built output with .dll+.pdb) is required" >&2; exit 2; }

if ! command -v infersharp >/dev/null 2>&1 && ! command -v infersharpaction >/dev/null 2>&1; then
  echo "NO-TOOL: Infer# CLI not available — skipping the build-required Infer# tier" >&2
  exit 3
fi

mkdir -p "$out"
# Infer# writes report.sarif into its output dir; copy it to the audit artifacts.
infersharp "$bin" --sarif --results-dir "$out/infer-out"
cp "$out/infer-out/report.sarif" "$out/infersharp.sarif"

echo "infersharp.sh: wrote $out/infersharp.sarif"
