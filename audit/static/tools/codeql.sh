#!/usr/bin/env bash
#
# Own.NET Audit — CodeQL runner (build-free tier).
#
# CodeQL can analyze C# straight from source with `--build-mode=none` (no MSBuild
# build of the target needed) — that is what makes it build-free (Plan.md §3.2).
#
# CRITICAL: the dispose / not-disposed queries live in the `security-and-quality`
# suite, NOT the default `security` suite. Using the default suite makes CodeQL
# silently return zero leak findings — a rake already documented in oracle.yml.
#
# Usage:
#   codeql.sh --target <src dir> --out <artifacts/own-audit> [--db <dir>]
#
# Emits: <out>/codeql.sarif. Exits 3 (NO-TOOL) if the codeql CLI is not installed,
# so the orchestrator records the tier as unavailable rather than failing the run.

set -euo pipefail

target=""
out="artifacts/own-audit"
db=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target) [[ $# -ge 2 ]] || { echo "codeql.sh: --target requires a value" >&2; exit 2; }
              target="$2"; shift 2 ;;
    --out)    [[ $# -ge 2 ]] || { echo "codeql.sh: --out requires a value" >&2; exit 2; }
              out="$2"; shift 2 ;;
    --db)     [[ $# -ge 2 ]] || { echo "codeql.sh: --db requires a value" >&2; exit 2; }
              db="$2"; shift 2 ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "codeql.sh: unknown arg $1" >&2; exit 2 ;;
  esac
done

[[ -n "$target" ]] || { echo "codeql.sh: --target is required" >&2; exit 2; }

if ! command -v codeql >/dev/null 2>&1; then
  echo "NO-TOOL: codeql CLI not installed — skipping the build-free CodeQL tier" >&2
  exit 3
fi

mkdir -p "$out"
db="${db:-$(mktemp -d)/codeql-db}"

# build-mode: none — analyze C# from source, no target build required.
codeql database create "$db" --language=csharp --build-mode=none --source-root="$target" --overwrite

# security-and-quality carries the dispose/leak quality queries (see header).
codeql database analyze "$db" \
  --format=sarifv2.1.0 \
  --output="$out/codeql.sarif" \
  codeql/csharp-queries:codeql-suites/csharp-security-and-quality.qls

echo "codeql.sh: wrote $out/codeql.sarif"
