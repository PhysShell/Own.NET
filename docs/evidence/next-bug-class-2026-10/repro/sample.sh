gh search code "CollectionsMarshal.GetValueRefOrAddDefault" --language "C#" --limit 60 --json repository,path,sha --jq '.[] | "\(.repository.nameWithOwner)\t\(.path)\t\(.sha)"' > sample/index.tsv
n=0
while IFS=$'\t' read -r repo path sha; do
  n=$((n+1)); out="sample/$n.cs"
  gh api "repos/$repo/git/blobs/$sha" --jq .content 2>/dev/null | base64 -d > "$out" 2>/dev/null || rm -f "$out"
done < sample/index.tsv
wc -l sample/index.tsv; ls sample/*.cs | wc -l
