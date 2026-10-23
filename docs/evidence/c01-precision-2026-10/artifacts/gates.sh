#!/usr/bin/env bash
# Own.NET gate run for C01-PRECISION-1 (baseline and patched use the same script).
# Usage: gates.sh <label>   -> logs in ~/Documents/ownnet-eng/work/logs/<label>/
# Runs inside WSL; tools come from one-off `nix shell` (nothing installed).
set -u
label=${1:?label}
steps=${2:-1234567}
run() { [[ "$steps" == *"$1"* ]]; }
R=~/Documents/ownnet-eng/Own.NET
L=~/Documents/ownnet-eng/work/logs/$label
CFG=~/Documents/ownnet-eng/work/nuget.isolated.config
mkdir -p "$L"
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 PYTHONUTF8=1
# keep the Windows PATH entries (interop) out of the way
export PATH=/run/current-system/sw/bin:/etc/profiles/per-user/nixos/bin:/usr/bin:/bin
cd "$R" || exit 1
stamp() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" | tee -a "$L/steps.log"; }
NIXPY="nix shell nixpkgs#python312 nixpkgs#dotnet-sdk_8 nixpkgs#git nixpkgs#jq --command"

stamp "start $label"
{ git rev-parse HEAD; git status --porcelain; git log --oneline -3; } > "$L/git.txt" 2>&1
stamp "git: $(head -1 "$L/git.txt") dirty=$(($(wc -l < "$L/git.txt") - 4))"

if run 1; then
# 1. Python core regression (AGENTS.md: python tests/run_tests.py)
nix shell nixpkgs#python312 nixpkgs#dotnet-sdk_8 nixpkgs#git nixpkgs#cargo nixpkgs#rustc nixpkgs#gcc --command python3 tests/run_tests.py > "$L/run_tests.txt" 2>&1; stamp "run_tests rc=$?"
fi

if run 2; then
# 2. lint gate (ruff check . + mypy)
nix shell nixpkgs#ruff --command ruff check . > "$L/ruff.txt" 2>&1; stamp "ruff rc=$?"
nix shell nixpkgs#mypy --command mypy > "$L/mypy.txt" 2>&1; stamp "mypy rc=$?"
fi

if run 3; then
# 3. extractor build, restore only through the nuget.org-only config
EX=frontend/roslyn/OwnSharp.Extractor/OwnSharp.Extractor.csproj
$NIXPY bash -c "dotnet restore $EX --configfile $CFG && dotnet build $EX -c Debug --no-restore" > "$L/build-extractor.txt" 2>&1
stamp "extractor build rc=$?"
fi

if run 4; then
# 4. extractor Tier-B tests that CI runs with dotnet present
for t in test_extractor_columns test_extractor_deep_flow test_extractor_sibling_locals test_extractor_partial_dispose test_guarded_consume; do
  OWN_TIERB_REQUIRED=1 $NIXPY python3 tests/$t.py > "$L/$t.txt" 2>&1; stamp "$t rc=$?"
done
fi

if run 5; then
# 5. CI samples job: extract the committed samples and run its grep assertions (ci.yml step
#    "Check facts through the core"), replayed by ci_samples.sh
$NIXPY bash ~/Documents/ownnet-eng/work/ci_samples.sh "$L" > "$L/ci_samples.txt" 2>&1; stamp "ci_samples rc=$?"
fi

if run 6; then
# 6. corpus benchmark on real C# (ci.yml corpus-benchmark; python engine, --min-recall 25)
$NIXPY python3 scripts/benchmark.py --min-recall 25 --json "$L/benchmark.json" > "$L/benchmark.txt" 2>&1
stamp "benchmark rc=$?"
fi

if run 7; then
# 7. Rust workspace: build own-cli + tests
( cd rust && nix shell nixpkgs#cargo nixpkgs#rustc nixpkgs#gcc --command bash -c "cargo build -p own-cli --release && cargo test -p own-cli && cargo test -p own-bridge" ) > "$L/rust.txt" 2>&1
stamp "rust build+test rc=$?"
fi
stamp done
