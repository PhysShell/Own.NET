#!/usr/bin/env bash
#
# The Stage-1 campaign layer: build the launcher the mutation just edited, then
# run the engine controls against it.
#
# A mutation campaign edits PRODUCTION source and asks whether the controls
# notice. For the Rust and Python layers elsewhere in this repository the test
# runner compiles the mutated source itself, so a layer is one command. The
# Stage-1 launcher is C#: `tests/test_stage1_engine.py` drives an already-built
# `ownsharp.dll`, so a mutation to CheckCommand.cs or CompareMode.cs would be
# invisible to it unless the binary is rebuilt first. This script is that
# "first" — it exists so a mutated launcher is the launcher under test, rather
# than yesterday's build wearing today's source.
#
# A build failure is a real outcome and exits non-zero: the campaign records it
# as a catch whose name says the layer failed, which is honest — a mutation
# that does not compile produced no evidence either way, and pretending it was
# "caught by a test" would inflate the campaign.
#
# Usage (from the repository root, as the campaign invokes it):
#   bash tests/stage1_campaign_layer.sh

set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

cli_proj="frontend/roslyn/OwnSharp.Cli/OwnSharp.Cli.csproj"
out="frontend/roslyn/OwnSharp.Cli/bin/Release/net8.0"

# Rebuild the launcher from the (possibly mutated) source.
if ! dotnet build "$cli_proj" -c Release --nologo -v q; then
  echo "stage1-layer: the launcher did not build" >&2
  exit 1
fi

# The vendored Python core is a PACK-time payload, so a plain build does not
# place it where the launcher looks. Stage it here for the Python-engine paths;
# this is harness setup, not a production behaviour.
mkdir -p "$out/ownlang-core/ownlang"
cp ownlang/*.py "$out/ownlang-core/ownlang/"

export OWEN_STAGE1_LAUNCHER_DLL="$root/$out/ownsharp.dll"
# Every control must actually run inside a campaign: a skipped control cannot
# catch a mutation, and a campaign whose denominator quietly shrank is exactly
# the zero-denominator "green" the P-022 discipline refuses.
export OWEN_STAGE1_REQUIRE=1

exec python3 tests/test_stage1_engine.py
