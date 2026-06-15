#!/usr/bin/env bash
#
# own-check — run the Own.NET C# leak check over a path.
#
# Chains the two halves of the P-001 pipeline into one command:
#
#   *.cs --[OwnSharp.Extractor (Roslyn)]--> facts.json --[python -m ownlang ownir]--> findings
#
# This is the body of the composite GitHub Action (action.yml) and also a
# standalone local command. There is one checker — the Python core; the C# side
# only extracts facts.
#
# Usage:
#   scripts/own-check.sh [--format human|github|msbuild] [--fail-on-finding]
#                        [--root <own.net checkout>] [--] <path|file> [more ...]
#
# Defaults: --format human, scans ".", does not fail the shell on findings,
# --root is the repo this script lives in. With --fail-on-finding the exit code
# is the core's (1 = leaks found). A hard error (bad facts) always exits non-zero.
#
# Requirements: a .NET SDK (`dotnet`) and Python 3.11+ on PATH.

set -euo pipefail

root=""
format="human"
fail_on_finding=0
paths=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root)            root="$2"; shift 2 ;;
    --format)          format="$2"; shift 2 ;;
    --fail-on-finding) fail_on_finding=1; shift ;;
    --)                shift; while [[ $# -gt 0 ]]; do paths+=("$1"); shift; done ;;
    -h|--help)         sed -n '2,30p' "$0"; exit 0 ;;
    *)                 paths+=("$1"); shift ;;
  esac
done

# Default root = the Own.NET checkout this script lives in (scripts/..).
if [[ -z "$root" ]]; then
  root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
if [[ ${#paths[@]} -eq 0 ]]; then
  paths=(".")
fi

extractor="$root/frontend/roslyn/OwnSharp.Extractor"
facts="$(mktemp)"
trap 'rm -f "$facts"' EXIT

# Stage 1: extract facts. dotnet's build/run chatter goes to stderr so stdout
# stays clean for the host-parseable findings (-o writes the facts to a file).
dotnet run --project "$extractor" --nologo -- "${paths[@]}" -o "$facts" 1>&2

# Stage 2: the one checker produces the verdict at the C# location.
set +e
PYTHONPATH="$root" python -m ownlang ownir "$facts" --format "$format"
rc=$?
set -e

# rc: 0 = clean, 1 = findings, >=2 = a hard error (bad facts / drifted contract).
if [[ "$fail_on_finding" -eq 1 ]]; then
  exit "$rc"
fi
if [[ "$rc" -ge 2 ]]; then
  exit "$rc"
fi
exit 0
