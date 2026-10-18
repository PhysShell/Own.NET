#!/usr/bin/env bash
# Check that every fetched sample file is byte-identical to its pinned blob (git hash-object = index SHA).
set -u
cd "$(dirname "$0")/.."
for round in 1 2; do
  ok=0; bad=0; missing=0; n=0
  while IFS=$'\t' read -r repo path sha; do
    n=$((n+1)); f="samples/r$round/$n.cs"
    if [ ! -f "$f" ]; then missing=$((missing+1))
    elif [ "$(git hash-object --no-filters "$f")" = "$sha" ]; then ok=$((ok+1))
    else bad=$((bad+1)); echo "MISMATCH r$round $n $repo $path"; fi
  done < "data/r$round/index.tsv"
  echo "r$round: ok=$ok mismatch=$bad missing=$missing"
done
