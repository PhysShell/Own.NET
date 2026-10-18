#!/usr/bin/env bash
# GitHub code search for one sample round; writes data/r<N>/raw.tsv and all.tsv (repo, path, blob sha).
# Usage: scripts/search.sh 1|2   (needs an authenticated `gh`). Code search results drift over time, so a
# re-run is NOT expected to reproduce the committed lists; the committed index.tsv files are the samples.
set -u
cd "$(dirname "$0")/.."
round=$1; out=data/r$round; mkdir -p "$out"; : > "$out/raw.tsv"
run() {
  gh search code "$@" --limit 100 --json repository,path,sha \
    --jq '.[] | "\(.repository.nameWithOwner)\t\(.path)\t\(.sha)"' >> "$out/raw.tsv" || true
  echo "after $*: $(wc -l < "$out/raw.tsv")"; sleep 8
}
if [ "$round" = 1 ]; then
  run GetValueRefOrNullRef --language "C#"
  run GetValueRefOrAddDefault --language "C#" --size "<3000"
  run GetValueRefOrAddDefault --language "C#" --size "3000..8000"
  run GetValueRefOrAddDefault --language "C#" --size "8000..20000"
  run GetValueRefOrAddDefault --language "C#" --size ">20000"
  run GetValueRefOrNullRef --language "C#" --size ">8000"
else
  run "GetValueRefOrAddDefault" "out bool" --language "C#"
  run "GetValueRefOrAddDefault" "out var exists" --language "C#"
  run "GetValueRefOrAddDefault" "out var found" --language "C#"
  run "GetValueRefOrAddDefault" "out _" --language "C#"
  run "GetValueRefOrAddDefault" "ref var" --language "C#"
  run "GetValueRefOrNullRef" "IsNullRef" --language "C#"
  run "GetValueRefOrAddDefault" Func --language "C#"
  run "GetValueRefOrAddDefault" lock --language "C#"
  run "GetValueRefOrAddDefault" --size "1500..2500" --language "C#"
  run "GetValueRefOrAddDefault" --size "5000..6500" --language "C#"
fi
LC_ALL=C sort -u "$out/raw.tsv" > "$out/all.tsv"; wc -l "$out/all.tsv"
