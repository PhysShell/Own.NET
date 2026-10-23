#!/usr/bin/env bash
# C01-PRECISION-1 sealed holdout job (inside qubix scanbox). Rules: docs/evidence/c01-precision-2026-10/holdout.md
# Part 1. Same scope copy for both analyzers; reserve repo only if a repo has < 50 .cs in scope or the
# baseline extractor fails on it.
set -u
. /job/sb-lib.sh
stamp "start holdout job, patch $(cat /job/PATCH_SHA)"
isolation
build_variant base "$in/ownnet-base.tar"
build_variant patched "$in/ownnet-patched.tar"

# scope copy: *.cs and *.xaml, no dir segment containing test|sample|demo|example|benchmark (case-insensitive),
# no bin/obj, *.g.cs, *.g.i.cs, *.Designer.cs (the extractor's own walk skips those too)
scope() {
  local src=$1 dst=$2
  mkdir -p "$dst"
  ( cd "$src" && find . -type f \( -name '*.cs' -o -name '*.xaml' \) \
      | grep -viE '/[^/]*(test|sample|demo|example|benchmark)[^/]*/' \
      | grep -vE '/(bin|obj)/|\.g\.cs$|\.g\.i\.cs$|\.Designer\.cs$' | sort ) > "$dst.list"
  ( cd "$src" && tar -cf - -T "$dst.list" ) | tar -xf - -C "$dst"
  grep -c '\.cs$' "$dst.list"
}

done_n=0
while IFS=$'\t' read -r -u 3 name url sha; do
  [ -z "$name" ] && continue
  [ "$done_n" -ge 3 ] && break
  r="$w/src-$name"; s="$w/scope-$name"
  fetch "$r" "$url" "$sha"
  n=$(scope "$r" "$s")
  cp "$s.list" "$out/scope-$name.list"
  stamp "$name $(git -C "$r" rev-parse HEAD) scope .cs files: $n"
  if [ "$n" -lt 50 ]; then stamp "$name: < 50 .cs in scope -> replaced by the next reserve"; continue; fi
  run_variant base "$name" "$s"
  if ! grep -q '^extractor_rc=0' "$out/run/$name/base/meta.txt"; then
    stamp "$name: baseline extractor failed -> replaced by the next reserve"; continue
  fi
  run_variant patched "$name" "$s"
  tar -czf "$out/scope-$name-src.tar.gz" -C "$s" .
  done_n=$((done_n + 1))
done 3< "$in/holdout.tsv"
stamp "holdout repos analysed: $done_n"
stamp done
exit 0
