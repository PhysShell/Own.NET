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
#   scripts/own-check.sh [--format human|github|msbuild|sarif] [--severity error|warning]
#                        [--fail-on-finding] [--legacy] [--stats] [--body-throw-edges]
#                        [--emit-facts <path>] [--config <own.toml>] [--root <own.net checkout>]
#                        [--] <path|file> [more ...]
#
# --config <own.toml> reads the project's [weak-subscription].subscribe wrapper
# names (P-035) and teaches the extractor to treat those calls as already-released
# weak subscriptions. A malformed config is a hard error.
#
# --emit-facts copies the OwnIR facts the extractor produced to <path> (the audit's
# XAML Phase-2 join consumes them alongside xaml-facts.json); the verdict is unchanged.
#
# Defaults: --format human, --severity error, scans ".", does not fail the shell
# on findings, --root is the repo this script lives in. --severity picks how a
# host shows findings (warning = advisory). With --fail-on-finding the exit code
# is the core's (1 = leaks found). A hard error (bad facts) always exits non-zero.
#
# Local IDisposables are checked by default with the path-sensitive flow analysis
# (--flow-locals): more precise (no Task/DataTable false positives; catches
# use-after-dispose / double-dispose / leak-on-a-path, any IDisposable type).
# Branches and while/foreach loops are analysed (P-016 A1); methods with a
# construct it can't model yet (for/do loops, try) are honestly skipped. --legacy
# falls back to the broad, name-based flat detector.
#
# Requirements: a .NET SDK (`dotnet`) and Python 3.11+ on PATH.

set -euo pipefail

root=""
format="human"
severity="error"
fail_on_finding=0
legacy=0
stats=0
body_throw_edges=0
emit_facts=""
config=""
paths=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root)
      [[ $# -ge 2 ]] || { echo "own-check: --root requires a value" >&2; exit 2; }
      root="$2"; shift 2 ;;
    --format)
      [[ $# -ge 2 ]] || { echo "own-check: --format requires a value" >&2; exit 2; }
      format="$2"; shift 2 ;;
    --severity)
      [[ $# -ge 2 ]] || { echo "own-check: --severity requires a value" >&2; exit 2; }
      severity="$2"; shift 2 ;;
    --emit-facts)
      [[ $# -ge 2 ]] || { echo "own-check: --emit-facts requires a value" >&2; exit 2; }
      emit_facts="$2"; shift 2 ;;
    --config)
      [[ $# -ge 2 ]] || { echo "own-check: --config requires a value" >&2; exit 2; }
      config="$2"; shift 2 ;;
    --fail-on-finding) fail_on_finding=1; shift ;;
    --legacy)          legacy=1; shift ;;
    --stats)           stats=1; shift ;;
    --body-throw-edges) body_throw_edges=1; shift ;;
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
# Default: the path-sensitive flow detector for local IDisposables (--flow-locals);
# --legacy keeps the flat name-based detector.
extractor_args=("${paths[@]}" -o "$facts")
[[ "$legacy" -eq 0 ]] && extractor_args+=(--flow-locals)
[[ "$stats" -eq 1 ]] && extractor_args+=(--stats)
# Opt-in P-016 throw tier: also flag body-level (no-try) dispose-not-called-on-throw — CodeQL
# cs/dispose-not-called-on-throw parity. CA2000-noisy, so off by default (oracle recall measurement).
[[ "$body_throw_edges" -eq 1 ]] && extractor_args+=(--body-throw-edges)
# P-035 / minimal P-015 (--config own.toml): read the project's declared
# weak-subscribe wrapper names ([weak-subscription].subscribe) and forward each to
# the extractor as an internal transport flag. The Python carrier is the one place
# that parses/validates the config; a malformed config is a hard error here.
if [[ -n "$config" ]]; then
  if ! weak_pairs="$(PYTHONPATH="$root" python -m ownlang config "$config")"; then
    exit 2
  fi
  while IFS= read -r pair; do
    [[ -n "$pair" ]] && extractor_args+=(--weak-subscribe "$pair")
  done <<< "$weak_pairs"
fi
dotnet run --project "$extractor" -- "${extractor_args[@]}" 1>&2

# Optional: persist the OwnIR facts (the audit's XAML Phase-2 join consumes them
# alongside xaml-facts.json). The verdict still comes from stage 2; this is just a
# copy of the intermediate the extractor already produced.
if [[ -n "$emit_facts" ]]; then
  cp "$facts" "$emit_facts"
fi

# Stage 2: the one checker produces the verdict at the C# location.
set +e
PYTHONPATH="$root" python -m ownlang ownir "$facts" --format "$format" --severity "$severity"
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
