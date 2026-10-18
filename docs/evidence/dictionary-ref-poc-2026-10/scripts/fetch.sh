#!/usr/bin/env bash
# Fetch the third-party inputs by pinned SHA (needs an authenticated `gh`). Nothing fetched is committed.
#   samples/r<N>/<n>.cs  line n of data/r<N>/index.tsv, by blob SHA
#   targets/<repo>-<base|fix>/  the two bug-fix pairs, by commit SHA
set -u
cd "$(dirname "$0")/.."
for round in 1 2; do
  mkdir -p "samples/r$round"; n=0
  while IFS=$'\t' read -r repo path sha; do
    n=$((n+1)); out="samples/r$round/$n.cs"
    [ -s "$out" ] || gh api "repos/$repo/git/blobs/$sha" --jq .content | base64 -d > "$out" || rm -f "$out"
  done < "data/r$round/index.tsv"
  echo "r$round: $(ls "samples/r$round" | wc -l) files"
done
get() {
  mkdir -p "targets/$1"
  gh api "repos/$2/contents/$3?ref=$4" -H "Accept: application/vnd.github.raw" > "targets/$1/$(basename "$3")"
}
get meziantou-base meziantou/Meziantou.Framework src/Meziantou.Framework/DictionaryExtensions.cs 7addb26cfd08a6ed6119a3d0a186486befaa923b
get meziantou-fix  meziantou/Meziantou.Framework src/Meziantou.Framework/DictionaryExtensions.cs cf82931e2cea86af40e67eb742f3c1331b65f91e
get maui-base dotnet/maui src/Controls/src/Core/BindableObject.cs 7b051d1bbf66d25a3b46c3382ffd25911f16c892
get maui-fix  dotnet/maui src/Controls/src/Core/BindableObject.cs 2db8b6af53b620f279d965f323d57f9d002c58da
