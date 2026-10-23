#!/usr/bin/env bash
# Build the two scanbox job dirs: same Own.NET subset as H1 (baseline = the H1 tar itself, byte for byte;
# patched = that tar with ONLY Program.cs replaced by the committed patch version).
set -eu
export PATH=/run/current-system/sw/bin:/usr/bin:/bin
W=~/Documents/ownnet-eng/work
H1TAR=~/Documents/ownnet-research/runs/H1/scanbox/job/ownnet-1750769-subset.tar
PATCH_SHA=$(cd ~/Documents/ownnet-eng/Own.NET && nix shell nixpkgs#git --command git rev-parse HEAD)
T=$(mktemp -d)
tar -xf "$H1TAR" -C "$T"
echo "subset files: $(tar -tf "$H1TAR" | grep -vc '/$')"
P=$(cd "$T" && find . -path '*OwnSharp.Extractor/Program.cs' | head -1)
echo "Program.cs in tar: $P"
tr -d '' < "$T/$P" | cmp -s - <(cd ~/Documents/ownnet-eng/Own.NET && nix shell nixpkgs#git --command git show 1750769:frontend/roslyn/OwnSharp.Extractor/Program.cs) \
  && echo "tar Program.cs == 1750769 (modulo CRLF, the H1 tar was packed from a Windows checkout): yes" || { echo "tar Program.cs differs from 1750769"; exit 1; }
(cd ~/Documents/ownnet-eng/Own.NET && nix shell nixpkgs#git --command git show "$PATCH_SHA:frontend/roslyn/OwnSharp.Extractor/Program.cs") | sed 's/$//' > "$T/$P"
for j in sb-dev sb-holdout; do
  mkdir -p "$W/$j"
  cp "$H1TAR" "$W/$j/ownnet-base.tar"
  (cd "$T" && tar -cf "$W/$j/ownnet-patched.tar" .)
  cp "$W/nuget.isolated.config" "$W/$j/"
  echo "$PATCH_SHA" > "$W/$j/PATCH_SHA"
done
rm -rf "$T"
sha256sum "$W"/sb-dev/*.tar
echo "patch sha $PATCH_SHA"
