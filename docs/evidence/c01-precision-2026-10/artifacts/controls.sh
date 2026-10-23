#!/usr/bin/env bash
# Compile the controls (scored cases must compile) and score them. Usage: controls.sh <before|after> <logdir>
set -u
phase=$1; L=$2; mkdir -p "$L"
export PATH=/run/current-system/sw/bin:/usr/bin:/bin DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
C=~/Documents/ownnet-eng/Own.NET/docs/evidence/c01-precision-2026-10/controls
CFG=~/Documents/ownnet-eng/work/nuget.isolated.config
B=~/Documents/ownnet-eng/work/controls-build   # build output kept OUT of the repo tree
cd ~/Documents/ownnet-eng/Own.NET || exit 1
nix shell nixpkgs#python312 nixpkgs#dotnet-sdk_8 --command bash -c "
  dotnet restore $C/Controls.csproj --configfile $CFG -p:BaseIntermediateOutputPath=$B/obj/ &&
  dotnet build $C/Controls.csproj --no-restore -p:BaseIntermediateOutputPath=$B/obj/ -p:OutputPath=$B/bin/ -warnaserror- 2>&1 | tail -5 &&
  dotnet build frontend/roslyn/OwnSharp.Extractor/OwnSharp.Extractor.csproj -v q --nologo --no-restore &&
  python3 $C/run_controls.py $phase $L/controls-$phase.json
" > "$L/controls-$phase.txt" 2>&1
echo "controls $phase rc=$?"
cat "$L/controls-$phase.txt" | tail -30
