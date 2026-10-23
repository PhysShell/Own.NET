#!/usr/bin/env bash
# Is the round7 failure caused by the patch or by the presence of a locally built own-cli?
export PATH=/run/current-system/sw/bin:/usr/bin:/bin
cd ~/Documents/ownnet-eng/Own.NET || exit 1
L=~/Documents/ownnet-eng/work/logs/patched
grep -rn "OwnSharp\|Program.cs\|extractor" tests/test_round7_apparatus.py scripts/round7/*.py | head -5
echo "--- with own-cli present (patched tree):"
nix shell nixpkgs#python312 nixpkgs#cargo nixpkgs#rustc nixpkgs#gcc --command python3 tests/test_round7_apparatus.py > "$L/round7-with-cli.txt" 2>&1; echo "rc=$?"
mv rust/target/release/own-cli /tmp/own-cli.aside
echo "--- full run_tests with own-cli moved aside (= baseline condition):"
nix shell nixpkgs#python312 nixpkgs#dotnet-sdk_8 nixpkgs#git nixpkgs#cargo nixpkgs#rustc nixpkgs#gcc --command python3 tests/run_tests.py > "$L/run_tests-no-cli.txt" 2>&1; echo "rc=$?"
mv /tmp/own-cli.aside rust/target/release/own-cli
grep -n "^FAIL" "$L/run_tests-no-cli.txt" | head
git status --porcelain
