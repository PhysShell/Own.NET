#!/usr/bin/env bash
# round7 apparatus on the BASELINE tree (exported copy, no .git) with the same own-cli present.
export PATH=/run/current-system/sw/bin:/usr/bin:/bin
B=/tmp/ownnet-base-1750769; rm -rf "$B"; mkdir -p "$B"
cd ~/Documents/ownnet-eng/Own.NET || exit 1
nix shell nixpkgs#git --command bash -c "git archive 1750769 | tar -x -C $B"
mkdir -p "$B/rust/target/release"; cp rust/target/release/own-cli "$B/rust/target/release/"
cd "$B" && nix shell nixpkgs#python312 nixpkgs#cargo nixpkgs#rustc nixpkgs#gcc --command python3 tests/test_round7_apparatus.py > ~/Documents/ownnet-eng/work/logs/baseline/round7-with-cli.txt 2>&1
echo "baseline round7 with own-cli rc=$?"
grep -n "^FAIL" ~/Documents/ownnet-eng/work/logs/baseline/round7-with-cli.txt | cut -c1-160
rm -rf "$B"
