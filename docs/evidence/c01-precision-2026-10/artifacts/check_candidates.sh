#!/usr/bin/env bash
# For each candidate owner/repo: is it (or its repo name) mentioned anywhere in prior research / mining?
cd ~/Documents/ownnet-eng/work || exit 1
for r in "$@"; do
  repo=${r#*/}
  exact=$(grep -ic "^${r}	" used-repos.tsv)
  byname=$(grep -iE "/${repo}	" used-repos.tsv | head -3 | cut -f1 | tr '\n' ' ')
  printf '%-34s exact=%s byname=[%s]\n' "$r" "$exact" "$byname"
done
