#!/usr/bin/env bash
S=/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad
export PATH=/root/.dotnet:$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
cd $S/lab/sc && python3 wholesrc.py SkiaSharp@4.148.0 && python3 derive_whole.py SkiaSharp@4.148.0
python3 $S/lab/witness/gen.py $S/lab/sc/witness-rows-tfm4.json $S/lab/sc/witness-results-tfm4.json > $S/lab/sc/witness-tfm4.log 2>&1
echo SKIA_DONE
