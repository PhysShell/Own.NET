#!/usr/bin/env bash
# witness pass 3 (sequential mode + repaired args, retries only rows without a fresh/cached verdict), then the
# receiver-ownership probe over the fresh rows with receivers, then the Stage E2 census chain
S=/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad
export PATH=/root/.dotnet:$PATH DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
python3 $S/lab/witness/gen.py $S/lab/sc/witness-rows.json $S/lab/sc/witness-results.json > $S/lab/sc/witness4.log 2>&1
python3 $S/lab/witness/gen.py $S/lab/sc/recvprobe-rows.json $S/lab/sc/recvprobe-results.json > $S/lab/sc/recvprobe.log 2>&1
echo OWNPROBE_DONE >> $S/lab/sc/recvprobe.log
bash $S/lab/sc/chain_e2.sh > $S/lab/sc/e2.log 2>&1
