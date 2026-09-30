#!/usr/bin/env bash
# TFM-targeted witnesses (Npgsql on net9.0 / net10.0 assets), then the Stage E2 census chain with the TFM-matched extractor
S=/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad
export PATH=/root/.dotnet:$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
python3 $S/lab/witness/gen.py $S/lab/sc/witness-rows-tfm.json $S/lab/sc/witness-results-tfm.json > $S/lab/sc/witness-tfm.log 2>&1
bash $S/lab/sc/chain_e2.sh > $S/lab/sc/e2.log 2>&1
