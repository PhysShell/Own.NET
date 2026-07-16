#!/usr/bin/env bash
# S1 orchestration — GLUE ONLY. Wires:
#   Own.NET render  ->  007 `o7 invoke`  ->  Own.NET validate-plan
# It does not read, interpret, or transform decisions; Own.NET owns render + validation,
# 007 owns the model call. It NEVER uses `o7 run`, never touches the source tree, always
# runs the model closed-world (read-only-data, explicit schema), and leaves no partial
# validated artifact on failure.
#
#   own-fix-plan.sh <candidates.json> <validated-plan.json> [--engine claude|codex] [--o7 <bin>]
set -euo pipefail

usage() {
  echo "usage: $0 <candidates.json> <validated-plan.json> [--engine claude|codex] [--o7 <o7-binary>]" >&2
  exit 2
}

engine="claude"
o7="o7"
positional=()
while [ $# -gt 0 ]; do
  case "$1" in
    --engine) engine="${2:?}"; shift 2 ;;
    --o7)     o7="${2:?}";     shift 2 ;;
    -h|--help) usage ;;
    --*) echo "own-fix-plan: unknown flag $1" >&2; usage ;;
    *) positional+=("$1"); shift ;;
  esac
done
[ "${#positional[@]}" -eq 2 ] || usage
candidates="${positional[0]}"
out="${positional[1]}"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
prompt="$work/prompt.txt"
schema="$work/fix-plan.schema.json"
rundir="$work/o7-out"

# 1. Own.NET: prompt + per-candidate schema (deterministic; no source, no spans).
python -m ownlang own-fix subscriptions render "$candidates" --prompt "$prompt" --schema "$schema"

# 2. 007: the closed-world, schema-bound model call. NOT `o7 run`.
"$o7" invoke --engine "$engine" --prompt-file "$prompt" --schema "$schema" \
  --capability-profile read-only-data --out "$rundir"

result="$rundir/result.json"
if [ ! -f "$result" ]; then
  echo "own-fix-plan: o7 invoke produced no result.json (see $rundir/meta.json)" >&2
  exit 1
fi

# 3. Own.NET: validate the UNTRUSTED result against the candidates + materialize. Written
#    inside the work dir first, then moved into place, so a failure leaves no partial out.
python -m ownlang own-fix subscriptions validate-plan "$candidates" "$result" \
  --output "$work/validated-plan.json"
mv "$work/validated-plan.json" "$out"
echo "own-fix-plan: validated plan -> $out"
